"""3ds Max translation endpoint for the shared Tech Connector rigging API."""

from __future__ import annotations

import json
import importlib
import re
from typing import Any, Iterable

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


HOST = "3dsmax"
RIG_BEHAVIOR_REVISION = 7


def reload_dependencies() -> int:
    """Refresh the shared portable contract used by this live Max host."""
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


def _rt():
    import pymxs

    return pymxs.runtime


def _result(ok: bool, capability: str, message: str = "", **kwargs: Any) -> dict[str, Any]:
    return RiggingOperationResult(ok, capability, HOST, message, **kwargs).to_dict()


def _node(name: str):
    node = _rt().getNodeByName(str(name))
    if node is None:
        raise ValueError(f"3ds Max node does not exist: {name}")
    return node


def _definition(value: Any) -> CharacterDefinition:
    if isinstance(value, CharacterDefinition):
        return value
    if isinstance(value, dict):
        if "schema" in value or "slots" in value:
            return CharacterDefinition.from_dict(value)
        return CharacterDefinition("Character", {str(key): str(node) for key, node in value.items() if node})
    raise ValueError("A portable character definition is required.")


def _matrix_values(matrix: Any) -> list[float]:
    rows = [matrix.row1, matrix.row2, matrix.row3, matrix.row4]
    return [
        float(rows[0].x), float(rows[0].y), float(rows[0].z), 0.0,
        float(rows[1].x), float(rows[1].y), float(rows[1].z), 0.0,
        float(rows[2].x), float(rows[2].y), float(rows[2].z), 0.0,
        float(rows[3].x), float(rows[3].y), float(rows[3].z), 1.0,
    ]


def _matrix_from_values(values: Iterable[float]):
    rt = _rt()
    data = [float(value) for value in values]
    if len(data) != 16:
        raise ValueError("A transform matrix requires 16 values")
    return rt.Matrix3(
        rt.Point3(data[0], data[1], data[2]),
        rt.Point3(data[4], data[5], data[6]),
        rt.Point3(data[8], data[9], data[10]),
        rt.Point3(data[12], data[13], data[14]),
    )


def _set_tag(node: Any, key: str, value: Any) -> None:
    _rt().setUserProp(node, str(key), str(value))


def _tag(node: Any, key: str) -> str:
    value = _rt().getUserProp(node, str(key))
    return "" if value is None else str(value)


def _set_if_property(target: Any, name: str, value: Any) -> bool:
    rt = _rt()
    try:
        if rt.isProperty(target, name):
            rt.setProperty(target, name, value)
            return True
    except Exception:
        pass
    return False


def _looks_like_joint(node: Any) -> bool:
    rt = _rt()
    try:
        names = " ".join((str(rt.classOf(node)), str(rt.classOf(node.baseObject)))).lower()
    except Exception:
        names = str(rt.classOf(node)).lower()
    return "bone" in names or "biped" in names or bool(_tag(node, "tc_joint"))


def _control(
    name: str,
    target: Any,
    module: str,
    *,
    size: float = 5.0,
    parent: Any = None,
    world_oriented: bool = False,
):
    rt = _rt()
    control = rt.getNodeByName(str(name))
    if control is None:
        control = rt.Point(
            name=str(name), size=max(float(size), 0.01), box=True,
            cross=False, centermarker=True, axistripod=False,
        )
    control.transform = (
        rt.Matrix3(
            rt.Point3(1.0, 0.0, 0.0),
            rt.Point3(0.0, 1.0, 0.0),
            rt.Point3(0.0, 0.0, 1.0),
            target.position,
        )
        if world_oriented
        else target.transform
    )
    if parent is not None:
        current_parent = getattr(control, "parent", None)
        current_handle = int(getattr(current_parent, "handle", 0) or 0)
        desired_handle = int(getattr(parent, "handle", 0) or 0)
        if current_handle != desired_handle:
            world_transform = control.transform
            control.parent = parent
            control.transform = world_transform
    _set_tag(control, "tc_rig_module", module)
    _set_tag(control, "tc_control_target", target.name)
    return control


def _mapped_mesh_fit_positions(definition: CharacterDefinition, mesh: Any) -> dict[str, list[float]]:
    """Fit mapped Max bone pivots into the selected mesh's world bounds."""
    rt = _rt()
    if mesh is None:
        raise ValueError("3ds Max joint placement requires a mesh node or semantic world positions.")
    rows = []
    for slot, joint_name in definition.slots.items():
        node = rt.getNodeByName(str(joint_name))
        if node is not None:
            rows.append((slot, node.position))
    if not rows:
        raise ValueError("The character definition has no resolvable 3ds Max bones to place.")
    bounds = rt.nodeGetBoundingBox(mesh, mesh.transform)
    try:
        target_min, target_max = bounds.min, bounds.max
    except AttributeError:
        target_min, target_max = bounds[0], bounds[1]
    def coordinates(point: Any) -> tuple[float, float, float]:
        return float(point.x), float(point.y), float(point.z)

    source_coordinates = [(slot, coordinates(point)) for slot, point in rows]
    source_min = [min(point[axis] for _slot, point in source_coordinates) for axis in range(3)]
    source_max = [max(point[axis] for _slot, point in source_coordinates) for axis in range(3)]
    target_min_values = list(coordinates(target_min))
    target_max_values = list(coordinates(target_max))
    fitted = {}
    for slot, point in source_coordinates:
        values = []
        for axis in range(3):
            source_span = source_max[axis] - source_min[axis]
            fraction = (
                (point[axis] - source_min[axis]) / source_span
                if abs(source_span) > 1.0e-8
                else 0.5
            )
            values.append(
                target_min_values[axis]
                + fraction * (target_max_values[axis] - target_min_values[axis])
            )
        fitted[slot] = values
    return fitted


def _append_targets(controller: Any, targets: list[Any], weights: list[float]) -> None:
    for target, weight in zip(targets, weights):
        controller.constraints.appendTarget(target, float(weight))


def _constrain(driven: Any, kind: str, drivers: list[Any], weights: list[float] | None = None) -> list[str]:
    rt = _rt()
    weights = list(weights or [100.0 / len(drivers)] * len(drivers))
    created = []
    if kind in {"point", "position", "parent"}:
        controller = rt.Position_Constraint()
        driven.position.controller = controller
        _append_targets(controller, drivers, weights)
        created.append(str(controller))
    if kind in {"orient", "rotate", "rotation", "parent"}:
        controller = rt.Orientation_Constraint()
        controller.relative = True
        driven.rotation.controller = controller
        _append_targets(controller, drivers, weights)
        created.append(str(controller))
    if kind == "scale":
        controller = rt.Scale_Constraint()
        driven.scale.controller = controller
        _append_targets(controller, drivers, weights)
        created.append(str(controller))
    if not created:
        raise ValueError(f"Unsupported 3ds Max constraint: {kind}")
    return created


def scene_joints() -> dict[str, Any]:
    rt = _rt()
    all_nodes = list(rt.objects)
    nodes = [node for node in all_nodes if _looks_like_joint(node)]
    if not nodes:
        nodes = [node for node in all_nodes if node.parent is not None or len(list(node.children)) > 0]
    rows = []
    for node in nodes:
        parent = node.parent
        depth, cursor = 0, parent
        while cursor is not None:
            depth += 1
            cursor = cursor.parent
        rows.append({
            "id": str(node.name), "native_id": str(node.handle), "name": str(node.name),
            "parent_id": str(parent.name) if parent is not None else "", "depth": depth,
            "local_matrix": _matrix_values(node.transform * rt.inverse(parent.transform)) if parent is not None else _matrix_values(node.transform),
            "world_matrix": _matrix_values(node.transform),
        })
    return _result(True, "host.query", data={"joints": rows})


def selection() -> dict[str, Any]:
    return _result(True, "host.query", data={"selection": [str(node.name) for node in list(_rt().selection)]})


def execute(capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = globals().get("_op_" + str(capability).replace(".", "_"))
    if handler is None:
        return _result(False, capability, f"3ds Max translation is not implemented: {capability}")
    try:
        if str(capability).startswith(("rig.", "skin.", "retarget.")):
            import pymxs
            with pymxs.undo(True, "Tech Connector: {}".format(capability)):
                return handler(dict(payload))
        return handler(dict(payload))
    except Exception as exc:
        return _result(False, capability, str(exc))


def _op_definition_auto_map(payload: dict[str, Any]) -> dict[str, Any]:
    rows = scene_joints()["data"]["joints"]
    definition = auto_map_character(
        rows, name=str(payload.get("name") or "Character"), source_provider=HOST,
        source_root=str(payload.get("root_joint") or ""),
    )
    validation = validate_character_definition(definition, rows)
    return _result(True, "definition.auto_map", f"Mapped {len(definition.slots)} 3ds Max bones.",
                   data={"definition": definition.to_dict(), "validation": validation.to_dict()},
                   warnings=validation.warnings)


def _op_definition_assign_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.slots[str(payload["slot"])] = str(_node(payload["joint"]).name)
    return _result(True, "definition.assign_slot", "Assigned 3ds Max character slot.",
                   data={"definition": definition.to_dict()})


def _op_definition_clear_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.slots.pop(str(payload["slot"]), None)
    return _result(True, "definition.clear_slot", "Cleared 3ds Max character slot.",
                   data={"definition": definition.to_dict()})


def _op_definition_mirror_slots(payload: dict[str, Any]) -> dict[str, Any]:
    definition = mirror_character_slots(_definition(payload.get("definition")), str(payload.get("source_side") or "left"))
    return _result(True, "definition.mirror_slots", "Mirrored 3ds Max slot assignments.",
                   data={"definition": definition.to_dict()})


def _op_definition_validate(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_character_definition(_definition(payload["mapping"]), scene_joints()["data"]["joints"])
    return _result(validation.ok, "definition.validate",
                   "Definition is valid." if validation.ok else "Definition needs attention.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_set_reference_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.reference_pose = {
        name: _matrix_values(_node(name).transform) for name in set(definition.slots.values())
    }
    return _result(True, "definition.set_reference_pose", "Captured 3ds Max reference pose.",
                   changed_ids=list(definition.reference_pose), data={"definition": definition.to_dict()})


def _op_definition_import(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.import", f"Loaded {definition.name}.", data={"definition": definition.to_dict()})


def _op_definition_export(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.export", f"Prepared {definition.name} for export.",
                   data={"definition": definition.to_dict()})


def _module_targets(module: str, definition: CharacterDefinition) -> list[tuple[str, str]]:
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
        "brows": ("LeftBrow", "RightBrow"), "eyes": ("LeftEye", "RightEye"),
        "jaw": ("Jaw",), "teeth": ("UpperTeeth", "LowerTeeth"),
        "nose": ("NoseRoot",),
    }
    if module not in routes:
        raise ValueError(f"3ds Max rig has no module route for {module}")
    return [(slot, definition.slots[slot]) for slot in routes[module] if definition.slots.get(slot)]


def _build_nose_module(definition: CharacterDefinition) -> list[str]:
    root_name = definition.slots.get("NoseRoot")
    if not root_name:
        raise ValueError("Character definition has no 3ds Max NoseRoot bone")
    root = _node(root_name)
    root_base = str(root.name)
    if root_base.endswith("_jnt"):
        root_base = root_base[:-4]
    root_control = _control(root_base + "_ctrl", root, "nose", size=4.0)
    _constrain(root, "parent", [root_control], [100.0])
    created = [str(root_control.name)]
    wanted = {"nose_upper", "nose_base", "nose_tip", "l_nostril", "r_nostril"}
    pending = list(root.children)
    while pending:
        child = pending.pop(0)
        pending.extend(list(child.children))
        base = str(child.name)
        if base.endswith("_jnt"):
            base = base[:-4]
        if base not in wanted:
            continue
        control = _control(base + "_ctrl", child, "nose", size=3.0, parent=root_control)
        _constrain(child, "parent", [control], [100.0])
        created.append(str(control.name))
    return created


def _build_thumb_rigs(definition: CharacterDefinition, blend: float) -> list[str]:
    """Build the Maya thumb-control contract with native Max HI IK."""
    rt = _rt()
    created = []
    for contract in thumb_rig_contract(definition):
        joints = [_node(joint_id) for joint_id in contract["joints"]]
        module = "fingers"
        parent_control = None
        for joint, control_name in zip(joints[:3], contract["fk_controls"]):
            control = _control(
                control_name,
                joint,
                module,
                size=max(float(getattr(joint, "width", 1.0) or 1.0), 0.25),
                parent=parent_control,
            )
            _set_tag(control, "tc_thumb_fk", True)
            _set_tag(control, "tc_channels_locked", False)
            parent_control = control
            created.append(str(control.name))

        ik_control = _control(
            contract["ik_control"], joints[-1], module,
            size=max(float(getattr(joints[-1], "width", 1.0) or 1.0), 0.25),
            world_oriented=True,
        )
        pole_control = _control(
            contract["pole_control"], joints[1], module,
            size=max(float(getattr(joints[1], "width", 1.0) or 1.0), 0.25),
            world_oriented=True,
        )

        thumb_line = joints[-1].position - joints[0].position
        line_length_squared = float(rt.dot(thumb_line, thumb_line))
        pole_origin = joints[1].position
        pole_direction = rt.Point3(0.0, 0.0, 0.0)
        for joint in joints[1:-1]:
            if line_length_squared > 1.0e-12:
                projection = joints[0].position + thumb_line * (
                    float(rt.dot(joint.position - joints[0].position, thumb_line))
                    / line_length_squared
                )
            else:
                projection = joints[0].position
            candidate = joint.position - projection
            if float(rt.length(candidate)) > float(rt.length(pole_direction)):
                pole_origin = projection
                pole_direction = candidate
        if float(rt.length(pole_direction)) <= 1.0e-8:
            source_axis = joints[0].transform.row3
            if line_length_squared > 1.0e-12:
                pole_direction = source_axis - thumb_line * (
                    float(rt.dot(source_axis, thumb_line)) / line_length_squared
                )
            else:
                pole_direction = source_axis
        if float(rt.length(pole_direction)) <= 1.0e-8:
            pole_direction = rt.Point3(0.0, 0.0, 1.0)
        pole_direction = rt.normalize(pole_direction)
        hand_slot = "LeftHand" if contract["side"] == "left" else "RightHand"
        hand_name = definition.slots.get(hand_slot)
        if hand_name:
            dorsal_direction = -_node(hand_name).transform.row3
            if float(rt.dot(dorsal_direction, rt.Point3(0.0, 0.0, 1.0))) < 0.0:
                dorsal_direction *= -1.0
            if line_length_squared > 1.0e-12:
                dorsal_direction -= thumb_line * (
                    float(rt.dot(dorsal_direction, thumb_line))
                    / line_length_squared
                )
            if (
                float(rt.length(dorsal_direction)) > 1.0e-8
                and float(rt.dot(pole_direction, dorsal_direction)) < 0.0
            ):
                pole_direction *= -1.0
        pole_control.position = pole_origin + pole_direction * 5.0
        _set_tag(pole_control, "tc_pole_side", contract["pole_side"])

        goal = rt.IKSys.ikChain(joints[0], joints[-1], "IKHISolver")
        if goal is None:
            raise RuntimeError("3ds Max did not create the thumb HI IK solver")
        goal.name = contract["ik_control"].removesuffix("_ctrl")
        goal_transform = goal.transform
        goal.parent = ik_control
        goal.transform = goal_transform
        controller = goal.transform.controller
        _set_if_property(controller, "VHTarget", pole_control)
        _set_if_property(controller, "VHUseTarget", True)
        _set_if_property(controller, "enabled", blend > 0.0)
        _set_if_property(controller, "IKBlend", blend)
        for node, role in (
            (ik_control, "ik"), (pole_control, "pole"), (goal, "solver")
        ):
            _set_tag(node, "tc_rig_module", module)
            _set_tag(node, "tc_thumb_role", role)
            _set_tag(node, "tc_thumb_contract_revision", contract["revision"])
            _set_tag(node, "tc_channels_locked", False)
        created.extend((str(ik_control.name), str(pole_control.name), str(goal.name)))
    return created


def _op_rig_create_control(payload: dict[str, Any]) -> dict[str, Any]:
    target = _node(payload["target"])
    name = str(payload.get("name") or f"{target.name}_ctrl")
    parent = _node(payload["parent"]) if payload.get("parent") else None
    control = _control(name, target, str(payload.get("module") or "custom"),
                       size=float(payload.get("size", 5.0) or 5.0), parent=parent)
    if bool(payload.get("constrain", True)):
        _constrain(target, "parent", [control], [100.0])
    return _result(True, "rig.create_control", "Created 3ds Max control.", created_ids=[str(control.name)])


def _op_rig_create_constraint(payload: dict[str, Any]) -> dict[str, Any]:
    driven = _node(payload["driven"])
    drivers = [_node(value) for value in payload["drivers"]]
    created = _constrain(driven, str(payload["type"]).lower(), drivers, payload.get("weights"))
    return _result(True, "rig.create_constraint", f"Created 3ds Max {payload['type']} constraint.",
                   created_ids=[f"{driven.name}:{index}" for index, _value in enumerate(created, 1)])


def _op_rig_create_ik_fk_limb(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    start, mid, end = (_node(payload[key]) for key in ("start", "mid", "end"))
    if mid.parent != start or end.parent != mid:
        raise ValueError("3ds Max IK Limb requires a contiguous start/mid/end hierarchy")
    module = str(payload.get("module") or f"{start.name}_limb")
    ik_control = _control(
        f"{end.name}_ik_ctrl",
        end,
        module,
        size=float(payload.get("size", 5.0) or 5.0),
        world_oriented=True,
    )
    pole_control = _control(
        f"{mid.name}_pole_ctrl",
        mid,
        module,
        size=float(payload.get("size", 5.0) or 5.0),
        world_oriented=True,
    )
    limb_line = end.position - start.position
    limb_length_squared = float(rt.dot(limb_line, limb_line))
    if limb_length_squared > 1.0e-8:
        projection = start.position + limb_line * (
            float(rt.dot(mid.position - start.position, limb_line)) / limb_length_squared
        )
        pole_direction = mid.position - projection
    else:
        pole_direction = rt.Point3(0.0, -1.0, 0.0)
    if float(rt.length(pole_direction)) <= 1.0e-8:
        pole_direction = rt.Point3(0.0, -1.0, 0.0)
    else:
        pole_direction = rt.normalize(pole_direction)
    pole_distance = max(
        float(rt.length(mid.position - start.position))
        + float(rt.length(end.position - mid.position)),
        0.1,
    )
    pole_control.position = mid.position + pole_direction * pole_distance
    goal = rt.IKSys.ikChain(start, end, "IKLimb")
    if goal is None:
        raise RuntimeError("3ds Max did not create the IK Limb solver")
    goal.name = f"{module}_ik_goal"
    goal_transform = goal.transform
    goal.parent = ik_control
    goal.transform = goal_transform
    controller = goal.transform.controller
    _set_if_property(controller, "VHTarget", pole_control)
    _set_if_property(controller, "VHUseTarget", True)
    stretch = max(0.0, min(1.0, float(payload.get("stretch", 0.0) or 0.0)))
    stretch_enabled = stretch > 0.0
    # Native 3ds Max bones change length from their child positions when
    # Freeze Length is disabled. Scale mode provides bidirectional limb
    # stretching without replacing the IK Limb solver.
    scale_mode = rt.Name("scale")
    for bone in (start, mid):
        _set_if_property(bone, "boneFreezeLength", not stretch_enabled)
        _set_if_property(bone, "boneScaleType", scale_mode)
    _set_tag(goal, "tc_rig_module", module)
    blend = max(0.0, min(1.0, float(payload.get("blend", 0.0) or 0.0)))
    _set_if_property(controller, "enabled", blend > 0.0)
    _set_if_property(controller, "IKBlend", blend)
    _set_tag(goal, "tc_ik_blend", blend)
    _set_tag(ik_control, "tc_stretch", stretch)
    _set_tag(start, "tc_stretch", stretch)
    _set_tag(mid, "tc_stretch", stretch)
    return _result(True, "rig.create_ik_fk_limb", "Created native 3ds Max IK Limb controls.",
                   created_ids=[str(ik_control.name), str(pole_control.name), str(goal.name)],
                   data={"limb": module, "ik_control": str(ik_control.name),
                         "pole_control": str(pole_control.name), "goal": str(goal.name),
                         "stretch_control": str(ik_control.name), "stretch_attribute": "tc_stretch",
                         "controls_world_oriented": True, "bind_pose_preserved": True,
                         "behavior_revision": RIG_BEHAVIOR_REVISION})


def _op_rig_create_curve_joints(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    curve = _node(payload["curve"])
    count = int(payload.get("joint_count", 5) or 5)
    if count < 1:
        raise ValueError("Joint count must be at least 1.")
    try:
        closed = bool(rt.isClosed(curve, 1))
        rt.resetLengthInterp()
        total_length = float(rt.curveLength(curve, 1))
    except Exception as exc:
        raise ValueError(f"Selected node is not a usable 3ds Max spline: {curve.name}") from exc
    if total_length <= 1.0e-8:
        raise ValueError("The selected curve has zero length.")

    denominator = count if closed else max(1, count - 1)
    parameters = [index / float(denominator) for index in range(count)]
    prefix = str(payload.get("name_prefix") or str(curve.name).removesuffix("_crv"))
    keep_attached = bool(payload.get("keep_attached", True))
    display_length = max(total_length / max(count * 3.0, 1.0), 0.05)
    joints = []
    constraints = []
    for index, parameter in enumerate(parameters, start=1):
        position = rt.lengthInterp(curve, 1, parameter)
        tangent = rt.lengthTangent(curve, 1, parameter)
        try:
            tangent = rt.normalize(tangent)
        except Exception:
            tangent = rt.Point3(1.0, 0.0, 0.0)
        up = rt.cross(tangent, rt.Point3(0.0, 0.0, 1.0))
        if float(rt.length(up)) <= 1.0e-8:
            up = rt.Point3(0.0, 1.0, 0.0)
        joint = rt.BoneSys.createBone(position, position + tangent * display_length, up)
        joint.name = f"{prefix}_path_{index:02d}_jnt"
        _set_tag(joint, "tc_curve_joint", True)
        _set_tag(joint, "tc_curve_parameter", parameter)
        if keep_attached:
            path_constraint = rt.Path_Constraint()
            joint.position.controller = path_constraint
            path_constraint.path = curve
            path_constraint.percent = parameter * 100.0
            path_constraint.constantVel = True
            path_constraint.follow = True
            path_constraint.loop = closed
            path_constraint.axis = 0
            constraints.append(str(path_constraint))
        joints.append(str(joint.name))
    return _result(
        True,
        "rig.create_curve_joints",
        f"Created {len(joints)} 3ds Max joints along the curve.",
        created_ids=joints,
        data={"joints": joints, "constraints": constraints, "parameters": parameters,
              "keep_attached": keep_attached, "closed": closed},
    )


def _op_rig_set_ik_fk_blend(payload: dict[str, Any]) -> dict[str, Any]:
    blend = max(0.0, min(1.0, float(payload["blend"])))
    module = str(payload["limb"])
    changed = []
    for node in list(_rt().objects):
        if _tag(node, "tc_rig_module") != module or not str(node.name).endswith("_ik_goal"):
            continue
        controller = node.transform.controller
        _set_if_property(controller, "enabled", blend > 0.0)
        _set_if_property(controller, "IKBlend", blend)
        _set_tag(node, "tc_ik_blend", blend)
        changed.append(str(node.name))
    return _result(bool(changed), "rig.set_ik_fk_blend",
                   "Updated 3ds Max IK blend." if changed else "IK limb was not found.", changed_ids=changed)


def _sample_positions(nodes: list[Any], count: int) -> list[Any]:
    rt = _rt()
    if count <= 1:
        return [nodes[0].position]
    start, end = nodes[0].position, nodes[-1].position
    return [start + (end - start) * (index / float(count - 1)) for index in range(count)]


def _op_rig_create_ribbon(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    chain = [_node(value) for value in payload["joint_chain"]]
    if len(chain) < 2:
        raise ValueError("A 3ds Max ribbon requires at least two joints")
    for parent, child in zip(chain, chain[1:]):
        if child.parent != parent:
            raise ValueError("3ds Max Spline IK requires a contiguous joint chain")
    module = str(payload.get("module") or payload.get("name") or f"{chain[0].name}_ribbon")
    goal = rt.IKSys.ikChain(chain[0], chain[-1], "SplineIKSolver")
    if goal is None:
        raise RuntimeError("3ds Max did not create the Spline IK solver")
    goal.name = f"{module}_spline_ik"
    controller = goal.transform.controller
    control_count = max(2, int(payload.get("control_count", 3) or 3))
    _set_if_property(controller, "autoSplineCreate", True)
    _set_if_property(controller, "splineKnotCount", control_count)
    _set_if_property(controller, "createHelper", True)
    _set_tag(goal, "tc_rig_module", module)
    _set_tag(goal, "tc_ribbon", True)
    _set_tag(goal, "tc_rig_region", str(payload.get("region") or "surface"))
    _set_tag(goal, "tc_rig_side", str(payload.get("side") or "c"))
    controls = []
    for index, position in enumerate(_sample_positions(chain, control_count), 1):
        helper = rt.Point(name=f"{module}_ctrl_{index:02d}", size=5.0, box=True, cross=False)
        helper.position = position
        _set_tag(helper, "tc_rig_module", module)
        _set_tag(helper, "tc_ribbon_control", index)
        controls.append(str(helper.name))
    return _result(True, "rig.create_ribbon", "Created native 3ds Max Spline IK ribbon.",
                   created_ids=[str(goal.name), *controls],
                   data={"module": module, "region": str(payload.get("region") or "surface"),
                         "side": str(payload.get("side") or "c"), "solver": str(goal.name), "controls": controls,
                         "bind_joints": [str(node.name) for node in chain]})


def _op_rig_create_twist(payload: dict[str, Any]) -> dict[str, Any]:
    start, end = _node(payload["start"]), _node(payload["end"])
    module = str(payload.get("module") or f"{start.name}_twist")
    start_parent = start.parent
    default_world_up = (
        str(start_parent.name)
        if start_parent is not None and _rt().isValidNode(start_parent)
        else str(start.name)
    )
    settings = twist_driver_contract(
        str(start.name),
        parent=str(payload.get("parent") or default_world_up),
        module=module,
        overrides=payload,
    )
    base_name = str(start.name)
    name = base_name[:-7] + "_twist_driver" if base_name.endswith("_driver") else base_name + "_twist_driver"
    twist_driver = _control(name, end, module, size=float(payload.get("size", 3.0) or 3.0), parent=start)
    _set_tag(twist_driver, "tc_twist_driver", True)
    _set_tag(twist_driver, "tc_twist_contract_revision", settings["revision"])
    _set_tag(twist_driver, "tc_world_up_bone", settings["world_up_object"])
    _set_tag(twist_driver, "tc_aim_target_bone", settings["aim_target"])
    _set_tag(twist_driver, "tc_world_up_vector", settings["world_up_vector"])
    _set_tag(twist_driver, "tc_up_vector", settings["up_vector"])
    _set_tag(twist_driver, "tc_maintain_offset", settings["maintain_offset"])
    _set_tag(twist_driver, "tc_constraint_weight", settings["weight"])
    if settings["aim_offset"] is not None:
        _set_tag(twist_driver, "tc_aim_offset", settings["aim_offset"])
    twist_nodes = [_node(value) for value in payload.get("twist_joints") or []]
    created = [str(twist_driver.name)]
    count = len(twist_nodes)
    for index, twist in enumerate(twist_nodes, 1):
        weight = index / float(count + 1)
        _constrain(twist, "orient", [start, end], [(1.0 - weight) * 100.0, weight * 100.0])
        _set_tag(twist, "tc_rig_module", module)
        created.append(str(twist.name))
    return _result(True, "rig.create_twist", "Created 3ds Max twist distribution.", created_ids=created,
                   data={"twist_driver": str(twist_driver.name), "parent": str(start.name),
                         "world_up_object": settings["world_up_object"],
                         "constraint_settings": settings})


def _op_skin_surface_spatial_smooth_brush(payload: dict[str, Any]) -> dict[str, Any]:
    from max_tools.Rigging import surface_spatial_skin_brush

    surface_spatial_skin_brush.show_ui()
    return _result(True, "skin.surface_spatial_smooth_brush",
                   "Opened the 3ds Max surface-spatial skin smoothing brush rollout.",
                   data={"ui": "TCSpatialSkinBrushRollout"})


def _op_rig_build_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    definition = _definition(payload["definition"])
    targets = _module_targets(module, definition)
    if not targets:
        raise ValueError(f"Character definition has no 3ds Max bones for module {module}")
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
        for slot, target_name in targets:
            if target_name in thumb_joint_ids:
                continue
            target = _node(target_name)
            control = _control(f"{slot}_ctrl", target, module)
            _constrain(target, "parent", [control], [100.0])
            created.append(str(control.name))
    elif module in {"left_arm", "right_arm", "left_leg", "right_leg"} and len(targets) >= 3:
        result = _op_rig_create_ik_fk_limb({
            "start": targets[0][1], "mid": targets[1][1], "end": targets[2][1], "module": module,
            "stretch": payload.get("stretch", 1.0),
            "blend": payload.get("blend", 0.0),
        })
        if not result["ok"]:
            raise RuntimeError(result["message"])
        created.extend(result["created_ids"])
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
        controls = []
        controls_by_slot = {}
        for slot, target_name in targets:
            target = _node(target_name)
            control = _control(names.get(slot, f"{slot}_ctrl"), target, module)
            driver = control
            if module == "spine" and slot != targets[-1][0]:
                sub_name = str(control.name).removesuffix("_ctrl") + "_sub_ctrl"
                sub_control = _control(
                    sub_name, target, module, parent=control
                )
                _set_tag(sub_control, "tc_shape_rotation_x", 90.0)
                _set_tag(sub_control, "tc_shape_rotation_space", "local_cvs")
                driver = sub_control
                created.append(str(sub_control.name))
            _constrain(target, "parent", [driver], [100.0])
            controls.append(control)
            controls_by_slot[slot] = control
            if module == "brows":
                _set_tag(control, "tc_shape_rotation_y", 90.0)
                _set_tag(control, "tc_shape_rotation_space", "local_cvs")
            created.append(str(control.name))
        if module == "brows":
            target_by_slot = dict(targets)
            for slot, prefix in (("LeftBrow", "l"), ("RightBrow", "r")):
                target_name = target_by_slot.get(slot)
                child = controls_by_slot.get(slot)
                if not target_name or child is None:
                    continue
                main = _control(
                    f"{prefix}_brow_main_ctrl", _node(target_name), module, size=7.5
                )
                _set_tag(main, "tc_shape_rotation_y", 90.0)
                _set_tag(main, "tc_shape_rotation_space", "local_cvs")
                child_world = child.transform
                child.parent = main
                child.transform = child_world
                created.append(str(main.name))
        if module == "mouth":
            parent = _control("lip_main_ctrl", _node(targets[0][1]), module, size=7.5)
            for control in controls:
                world_transform = control.transform
                control.parent = parent
                control.transform = world_transform
            created.insert(0, str(parent.name))
    return _result(True, "rig.build_module", f"Built 3ds Max module {module}.",
                   created_ids=created, data={
                       "module": module,
                       "brow_shape_rotation_y": 90.0 if module == "brows" else None,
                       "spine_sub_shape_rotation_x": 90.0 if module == "spine" else None,
                   })


def _apply_face_joint_placement_rules(mesh: Any = None) -> dict[str, Any]:
    """Apply brow arc frames and terminal facial channel rules in Max."""
    rt = _rt()
    nodes = list(rt.objects)

    def short_name(node: Any) -> str:
        return str(node.name).rsplit(":", 1)[-1]

    mesh_center = mesh.center if mesh is not None else rt.Point3(0.0, 0.0, 0.0)
    brow_report = {}
    changed = []
    for side in ("l", "r"):
        rows = []
        for node in nodes:
            match = re.match(rf"^{side}_brow(\d+|_end)$", short_name(node), re.IGNORECASE)
            if match:
                token = match.group(1).lower()
                rows.append((6 if token == "_end" else int(token), node))
        rows.sort(key=lambda row: row[0])
        if len(rows) < 2:
            continue
        brow_nodes = [node for _index, node in rows]
        previous_y = None
        for index, node in enumerate(brow_nodes):
            x_axis = rt.normalize(
                brow_nodes[index + 1].position - node.position
                if index < len(brow_nodes) - 1
                else node.position - brow_nodes[index - 1].position
            )
            normal = node.position - mesh_center
            normal = normal - x_axis * float(rt.dot(normal, x_axis))
            if float(rt.length(normal)) <= 1.0e-8:
                normal = node.transform.row3
                normal = normal - x_axis * float(rt.dot(normal, x_axis))
            normal = rt.normalize(normal)
            y_axis = rt.normalize(rt.cross(normal, x_axis))
            if float(rt.dot(y_axis, rt.Point3(0.0, 0.0, 1.0))) < 0.0:
                y_axis = -y_axis
                normal = -normal
            z_axis = rt.normalize(rt.cross(x_axis, y_axis))
            node.transform = rt.Matrix3(x_axis, y_axis, z_axis, node.position)
            brow_report[short_name(node)] = {
                "x_next_brow_alignment": 1.0,
                "y_surface_tangent_alignment": 1.0,
                "adjacent_y_alignment": float(rt.dot(previous_y, y_axis)) if previous_y is not None else 1.0,
            }
            previous_y = y_axis
            changed.append(str(node.name))

    surface_report = {}

    def orient_surface_node(node: Any, _tangent_reference: Any) -> None:
        normal = node.position - mesh_center
        if float(rt.length(normal)) <= 1.0e-8:
            normal = node.transform.row3
        normal = rt.normalize(normal)
        world_up = rt.Point3(0.0, 0.0, 1.0)
        y_axis = world_up - normal * float(rt.dot(world_up, normal))
        if float(rt.length(y_axis)) <= 1.0e-8:
            current_y = node.transform.row2
            y_axis = current_y - normal * float(rt.dot(current_y, normal))
        if float(rt.length(y_axis)) <= 1.0e-8:
            return
        y_axis = rt.normalize(y_axis)
        x_axis = rt.normalize(rt.cross(y_axis, normal))
        z_axis = rt.normalize(rt.cross(x_axis, y_axis))
        node.transform = rt.Matrix3(x_axis, y_axis, z_axis, node.position)
        surface_report[short_name(node)] = {
            "x_surface_tangent_alignment": 1.0,
            "y_outward_view_up_alignment": float(rt.dot(y_axis, world_up)),
            "z_surface_normal_alignment": abs(float(rt.dot(z_axis, normal))),
        }
        changed.append(str(node.name))

    for side in ("l", "r"):
        under_rows = []
        for node in nodes:
            match = re.match(
                rf"^{side}_under_?eye_?(\d+)$",
                short_name(node),
                re.IGNORECASE,
            )
            if match:
                under_rows.append((int(match.group(1)), node))
        under_rows.sort(key=lambda row: row[0])
        under_nodes = [node for _index, node in under_rows]
        for index, node in enumerate(under_nodes):
            neighbor = (
                under_nodes[index + 1]
                if index < len(under_nodes) - 1
                else under_nodes[index - 1] if index else None
            )
            if neighbor is not None:
                direction = (
                    neighbor.position - node.position
                    if index < len(under_nodes) - 1
                    else node.position - neighbor.position
                )
                orient_surface_node(node, direction)
        for node in nodes:
            if re.match(
                rf"^{side}_.+cheek.*$",
                short_name(node),
                re.IGNORECASE,
            ):
                orient_surface_node(node, node.transform.row1)

    eyelid_tips = []
    tip_pattern = re.compile(r"^(?:l|r)_(?:inner|outer|upper|lower)_eyelidTip\d*$", re.IGNORECASE)
    for node in nodes:
        if not tip_pattern.match(short_name(node)):
            continue
        parent = node.parent
        source = parent.transform if parent is not None else rt.Matrix3(1)
        node.transform = rt.Matrix3(
            rt.normalize(source.row1), rt.normalize(source.row2), rt.normalize(source.row3), node.position
        )
        _set_tag(node, "tc_rotate_channels", "0,0,0")
        eyelid_tips.append(str(node.name))

    nose_base = next((node for node in nodes if short_name(node).lower() == "nose_base"), None)
    if nose_base is not None:
        if nose_base.parent is not None:
            local_position = nose_base.position * rt.inverse(nose_base.parent.transform)
            local_position.x = 0.0
            nose_base.position = local_position * nose_base.parent.transform
        else:
            position = nose_base.position
            position.x = 0.0
            nose_base.position = position
        _set_tag(nose_base, "tc_translate_x", 0.0)
        changed.append(str(nose_base.name))
    return {
        "brows": brow_report,
        "surface_face": surface_report,
        "eyelid_tip_zero_rotates": eyelid_tips,
        "nose_base_translate_x": 0.0 if nose_base is not None else None,
        "changed_ids": list(dict.fromkeys(changed + eyelid_tips)),
    }


def _delete_auto_joint_guides() -> list[str]:
    """Remove the temporary placement guide hierarchy after an apply."""
    rt = _rt()
    group = rt.getNodeByName("auto_joint_guides_grp")
    if group is None:
        return []
    nodes = []
    pending = [group]
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending.extend(list(node.children))
    removed = [str(node.name) for node in nodes]
    for node in reversed(nodes):
        if rt.isValidNode(node):
            rt.delete(node)
    return removed


def _op_rig_place_joints(payload: dict[str, Any]) -> dict[str, Any]:
    """Place mapped Max bones from explicit points or a selected mesh fit."""
    rt = _rt()
    definition = _definition(payload["definition"])
    positions = dict(payload.get("positions") or {})
    mesh = rt.getNodeByName(str(payload.get("mesh") or ""))
    if not positions:
        if mesh is None:
            mesh = next(iter(list(rt.selection)), None)
        positions = _mapped_mesh_fit_positions(definition, mesh)
    if bool(payload.get("preview", False)):
        return _result(
            True,
            "rig.place_joints",
            "Previewed 3ds Max character joint placement.",
            data={"positions": positions, "applied": False, "behavior_revision": RIG_BEHAVIOR_REVISION},
        )
    changed = []
    for key, values in positions.items():
        joint_name = definition.slots.get(str(key), str(key))
        node = _node(joint_name)
        node.position = rt.Point3(*[float(value) for value in values])
        changed.append(str(node.name))
    face_rules = _apply_face_joint_placement_rules(mesh)
    changed.extend(face_rules.pop("changed_ids"))
    removed_guides = _delete_auto_joint_guides()
    return _result(
        True,
        "rig.place_joints",
        "Placed 3ds Max character joints.",
        changed_ids=changed,
        data={"positions": positions, "applied": True, "face_orientation": face_rules,
              "removed_auto_joint_guides": removed_guides,
              "behavior_revision": RIG_BEHAVIOR_REVISION},
    )


def _op_rig_set_t_pose(payload: dict[str, Any]) -> dict[str, Any]:
    """Set a mapped 3ds Max skeleton to a world-axis T-pose."""
    rt = _rt()
    definition = _definition(payload["definition"])
    pose_matrices = dict(payload.get("pose_matrices") or {})
    changed = []
    if pose_matrices:
        for key, values in pose_matrices.items():
            joint_name = definition.slots.get(str(key), str(key))
            node = _node(joint_name)
            node.transform = _matrix_from_values(values)
            changed.append(str(node.name))
        return _result(True, "rig.set_t_pose", "Applied portable 3ds Max T-pose matrices.", changed_ids=changed)

    def aim_nodes(joint_name: Any, child_name: Any, target_values: Any) -> None:
        if not joint_name or not child_name:
            return
        node, child = _node(joint_name), _node(child_name)
        segment = rt.normalize(child.position - node.position)
        local_sign = 1.0 if rt.dot(node.transform.row1, segment) >= 0.0 else -1.0
        target_vector = (
            rt.Point3(float(target_values.x), float(target_values.y), float(target_values.z))
            if hasattr(target_values, "x")
            else rt.Point3(*target_values)
        )
        x_axis = rt.normalize(target_vector * local_sign)
        reference = rt.Point3(0.0, 0.0, 1.0)
        if abs(float(rt.dot(x_axis, reference))) > 0.95:
            reference = rt.Point3(0.0, 1.0, 0.0)
        z_axis = rt.normalize(rt.cross(x_axis, reference))
        y_axis = rt.normalize(rt.cross(z_axis, x_axis))
        node.transform = rt.Matrix3(x_axis, y_axis, z_axis, node.position)
        changed.append(str(node.name))

    def aim(slot: str, child_slot: str, target_values: tuple[float, float, float]) -> None:
        aim_nodes(definition.slots.get(slot), definition.slots.get(child_slot), target_values)

    for slot in ("Reference", "Hips"):
        joint_name = definition.slots.get(slot)
        if joint_name:
            node = _node(joint_name)
            node.transform = rt.Matrix3(
                rt.Point3(1.0, 0.0, 0.0),
                rt.Point3(0.0, 1.0, 0.0),
                rt.Point3(0.0, 0.0, 1.0),
                node.position,
            )
            changed.append(str(node.name))

    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        aim(side + "Arm", side + "ForeArm", (sign, 0.0, 0.0))
        aim(side + "ForeArm", side + "Hand", (sign, 0.0, 0.0))
        aim(side + "UpLeg", side + "Leg", (0.0, 0.0, -1.0))
        aim(side + "Leg", side + "Foot", (0.0, 0.0, -1.0))
        foot_name = definition.slots.get(side + "Foot")
        toe_name = definition.slots.get(side + "ToeBase")
        if foot_name and toe_name:
            foot, toe = _node(foot_name), _node(toe_name)
            foot_direction = toe.position - foot.position
            foot_direction.z = 0.0
            if float(rt.length(foot_direction)) > 1.0e-8:
                aim_nodes(foot_name, toe_name, foot_direction)
            toe_children = list(toe.children)
            if toe_children:
                toe_direction = toe_children[0].position - toe.position
                toe_direction.z = 0.0
                if float(rt.length(toe_direction)) > 1.0e-8:
                    aim_nodes(toe_name, str(toe_children[0].name), toe_direction)

    grounded_by = 0.0
    if bool(payload.get("ground", True)):
        contact_heights = []
        for side in ("Left", "Right"):
            for slot in (side + "Foot", side + "ToeBase"):
                name = definition.slots.get(slot)
                if name:
                    contact_heights.append(float(_node(name).position.z))
        hips_name = definition.slots.get("Hips")
        if contact_heights and hips_name:
            grounded_by = -min(contact_heights)
            hips = _node(hips_name)
            hips.position = hips.position + rt.Point3(0.0, 0.0, grounded_by)
            changed.append(str(hips.name))
    return _result(
        True,
        "rig.set_t_pose",
        "Set 3ds Max character T-pose.",
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
    modules = list(payload.get("modules") or (
        "root", "pelvis", "spine", "neck", "head",
        "left_arm", "right_arm", "left_leg", "right_leg", "fingers",
    ))
    optional = {
        "mouth": ("UpperLipCenter", "LowerLipCenter", "LeftLipCorner", "RightLipCorner"),
        "eyes": ("LeftEye", "RightEye"), "brows": ("LeftBrow", "RightBrow"),
        "jaw": ("Jaw",), "teeth": ("UpperTeeth", "LowerTeeth"),
        "nose": ("NoseRoot",),
    }
    if not payload.get("modules"):
        modules.extend(module for module, slots in optional.items() if any(definition.slots.get(slot) for slot in slots))
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
    return _result(not warnings, "rig.build_full", f"Built {len(modules) - len(warnings)} 3ds Max rig modules.",
                   created_ids=created, warnings=warnings, data={
                       "modules": modules,
                       "t_pose": t_pose_result,
                       "behavior_revision": RIG_BEHAVIOR_REVISION,
                   })


def _op_rig_remove_module(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    module = str(payload["module"]).lower()
    removed = []
    for node in list(rt.objects):
        if _tag(node, "tc_rig_module").lower() == module:
            removed.append(str(node.name))
            rt.delete(node)
    return _result(True, "rig.remove_module", f"Removed 3ds Max module {module}.", removed_ids=removed)


def _op_rig_rebuild_module(payload: dict[str, Any]) -> dict[str, Any]:
    removed = _op_rig_remove_module(payload)
    built = _op_rig_build_module(payload)
    built["capability"] = "rig.rebuild_module"
    built["removed_ids"] = removed["removed_ids"]
    return built


def _op_rig_create_face_module(payload: dict[str, Any]) -> dict[str, Any]:
    return _op_rig_build_module(payload)


def _op_retarget_create_definition(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["mapping"])
    return _result(True, "retarget.create_definition", f"Created {definition.name} retarget definition.",
                   data={"definition": definition.to_dict()})


def _op_retarget_validate_definition(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_character_definition(_definition(payload["definition"]), scene_joints()["data"]["joints"])
    return _result(validation.ok, "retarget.validate_definition",
                   "Retarget definition is valid." if validation.ok else "Retarget definition needs attention.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _op_retarget_solve_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    changed = []
    for slot, values in dict(payload["source"]).items():
        target_name = definition.slots.get(slot)
        if target_name and isinstance(values, (list, tuple)) and len(values) == 16:
            target = _node(target_name)
            target.transform = _matrix_from_values(values)
            changed.append(str(target.name))
    return _result(True, "retarget.solve_pose", f"Solved {len(changed)} 3ds Max joints.", changed_ids=changed)


_op_retarget_preview = _op_retarget_solve_pose


def _op_rig_edit_control_shape(payload: dict[str, Any]) -> dict[str, Any]:
    control = _node(payload["control"])
    shape = str(payload.get("shape") or "")
    if payload.get("size") is not None:
        _set_if_property(control, "size", max(0.01, float(payload["size"])))
    if shape:
        _set_tag(control, "tc_control_shape", shape)
    if "cv_positions" in payload:
        _set_tag(control, "tc_control_cv_positions", json.dumps(payload.get("cv_positions") or []))
    return _result(True, "rig.edit_control_shape", "Updated 3ds Max control shape.", changed_ids=[str(control.name)])


def _op_rig_create_reverse_foot(payload: dict[str, Any]) -> dict[str, Any]:
    ankle, ball, toe = (_node(payload[key]) for key in ("ankle", "ball", "toe"))
    module = str(payload.get("module") or f"{ankle.name}_reverse_foot")
    parent = None
    created = []
    for role, target in (("heel", ankle), ("toe", toe), ("ball", ball), ("ankle", ankle)):
        control = _control(f"{module}_{role}_pivot", target, module,
                           size=float(payload.get("size", 3.0) or 3.0), parent=parent)
        _set_tag(control, "tc_reverse_foot_role", role)
        created.append(str(control.name))
        parent = control
    _constrain(ankle, "parent", [parent], [100.0])
    return _result(True, "rig.create_reverse_foot", "Created 3ds Max reverse-foot pivots.", created_ids=created)


def _op_rig_create_motion_path(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    target, curve = _node(payload["target"]), _node(payload["curve"])
    controller = rt.Path_Constraint()
    target.position.controller = controller
    controller.path = curve
    controller.percent = float(payload.get("parameter", 0.0) or 0.0) * 100.0
    controller.constantVel = True
    controller.follow = bool(payload.get("follow", True))
    _set_tag(target, "tc_motion_path", str(curve.name))
    return _result(True, "rig.create_motion_path", "Created 3ds Max path constraint.",
                   created_ids=[f"{target.name}:Path_Constraint"])


def _op_rig_create_space_switch(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    driven = _node(payload["driven"])
    targets = [_node(value) for value in payload["targets"]]
    names = [str(value) for value in (payload.get("names") or [target.name for target in targets])]
    active = int(payload.get("active", 0) or 0)
    mode = str(payload.get("mode") or "parent").lower()
    created = []
    if mode in {"parent", "point"}:
        position = rt.Position_Constraint()
        driven.position.controller = position
        for index, target in enumerate(targets):
            position.appendTarget(target, 100.0 if index == active else 0.0)
        created.append(f"{driven.name}:Position_Constraint")
    if mode in {"parent", "orient", "rotate"}:
        rotation = rt.Orientation_Constraint()
        driven.rotation.controller = rotation
        for index, target in enumerate(targets):
            rotation.appendTarget(target, 100.0 if index == active else 0.0)
        created.append(f"{driven.name}:Orientation_Constraint")
    switch_id = str(payload.get("name") or f"TC_{driven.name}_space")
    _set_tag(driven, "tc_space_switch", json.dumps({
        "id": switch_id, "targets": [str(target.name) for target in targets],
        "names": names, "active": active, "mode": mode,
    }))
    return _result(True, "rig.create_space_switch", "Created 3ds Max space switch.", created_ids=created,
                   data={"space_switch": f"{driven.name}|{switch_id}"})


def _set_constraint_weights(controller: Any, active: int) -> None:
    count = int(getattr(controller, "getNumTargets")())
    for index in range(1, count + 1):
        controller.setWeight(index, 100.0 if index - 1 == active else 0.0)


def _op_rig_set_space(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload["space_switch"])
    node_name = token.split("|", 1)[0]
    driven = _node(node_name)
    metadata = json.loads(_tag(driven, "tc_space_switch") or "{}")
    names = list(metadata.get("names") or [])
    requested = payload["space"]
    active = names.index(requested) if isinstance(requested, str) and requested in names else int(requested)
    if active < 0 or active >= len(names):
        raise IndexError("Space index is outside the switch target range")
    changed = []
    for label, controller in (("position", driven.position.controller), ("rotation", driven.rotation.controller)):
        try:
            _set_constraint_weights(controller, active)
            changed.append(f"{driven.name}:{label}")
        except Exception:
            continue
    metadata["active"] = active
    _set_tag(driven, "tc_space_switch", json.dumps(metadata))
    return _result(bool(changed), "rig.set_space", "Updated 3ds Max active space.", changed_ids=changed)


def _op_rig_create_mesh_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    driven, mesh = _node(payload["driven"]), _node(payload["mesh"])
    try:
        controller = rt.Surface()
    except Exception:
        controller = rt.Surface_Constraint()
    driven.position.controller = controller
    controller.surface = mesh
    uv = list(payload.get("uv") or (0.5, 0.5))
    _set_if_property(controller, "U_Position", float(uv[0]) * 100.0)
    _set_if_property(controller, "V_Position", float(uv[1]) * 100.0)
    _set_tag(driven, "tc_mesh_attachment", str(mesh.name))
    return _result(True, "rig.create_mesh_attachment", "Created 3ds Max surface attachment.",
                   created_ids=[f"{driven.name}:Surface_Constraint"])


def _op_rig_create_pose_reader(payload: dict[str, Any]) -> dict[str, Any]:
    rt = _rt()
    driver = _node(payload["driver"])
    name = str(payload.get("name") or f"{driver.name}_pose_reader")
    try:
        reader = rt.ExposeTm(name=name)
        reader.exposeNode = driver
    except Exception:
        reader = rt.Point(name=name, size=float(payload.get("size", 2.0) or 2.0), box=False, cross=True)
        reader.transform = driver.transform
    _set_tag(reader, "tc_pose_reader", True)
    _set_tag(reader, "tc_pose_reader_driver", str(driver.name))
    _set_tag(reader, "tc_pose_reader_axis", str(payload.get("axis") or "x"))
    _set_tag(reader, "tc_pose_reader_range", json.dumps(payload.get("range") or [-90.0, 90.0]))
    _set_tag(reader, "tc_pose_reader_output", 0.0)
    return _result(True, "rig.create_pose_reader", "Created 3ds Max pose reader helper.", created_ids=[str(reader.name)])


def _connection_store_node():
    rt = _rt()
    node = rt.getNodeByName("TC_RigConnectionStore")
    if node is None:
        node = rt.Point(name="TC_RigConnectionStore", size=1.0, box=False, cross=False)
        node.isHidden = True
    return node


def _op_rig_store_connections(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"])
    rows = []
    for node in list(_rt().objects):
        if _tag(node, "tc_rig_module") != module:
            continue
        rows.append({"node": str(node.name), "parent": str(node.parent.name) if node.parent else "",
                     "transform": _matrix_values(node.transform), "module": module})
    _set_tag(_connection_store_node(), f"tc_connections_{module}", json.dumps(rows))
    return _result(True, "rig.store_connections", f"Stored {len(rows)} 3ds Max module connections.",
                   data={"connections": rows})


def _op_rig_restore_connections(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"])
    rows = json.loads(_tag(_connection_store_node(), f"tc_connections_{module}") or "[]")
    changed = []
    for row in rows:
        node = _rt().getNodeByName(str(row.get("node") or ""))
        if node is None:
            continue
        parent = _rt().getNodeByName(str(row.get("parent") or ""))
        world = _matrix_from_values(row["transform"])
        if parent is not None:
            node.parent = parent
        node.transform = world
        changed.append(str(node.name))
    return _result(True, "rig.restore_connections", f"Restored {len(changed)} 3ds Max module connections.",
                   changed_ids=changed, data={"connections": rows})


def _op_retarget_preview(payload: dict[str, Any]) -> dict[str, Any]:
    result = _op_retarget_solve_pose(payload)
    result["capability"] = "retarget.preview"
    return result


def _op_retarget_bake(payload: dict[str, Any]) -> dict[str, Any]:
    import pymxs

    rt = _rt()
    definition = _definition(payload["target"])
    start, end = (int(round(float(value))) for value in payload["range"])
    step = max(1, int(round(float(payload.get("sample_rate", 1) or 1))))
    changed = []
    for target_name in definition.slots.values():
        target = rt.getNodeByName(str(target_name))
        if target is None:
            continue
        for frame in range(start, end + 1, step):
            with pymxs.animate(True):
                with pymxs.attime(frame):
                    target.transform = target.transform
        changed.append(str(target.name))
    return _result(True, "retarget.bake", "Baked retargeted 3ds Max animation.", changed_ids=changed)


def _op_retarget_transfer_take(payload: dict[str, Any]) -> dict[str, Any]:
    take = payload["take"]
    _set_tag(_connection_store_node(), "tc_retarget_take", json.dumps(take, default=str))
    return _result(True, "retarget.transfer_take", "Stored 3ds Max retarget take metadata.", data={"take": take})
