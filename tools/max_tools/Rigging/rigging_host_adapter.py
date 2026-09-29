"""3ds Max translation endpoint for the shared Tech Connector rigging API."""

from __future__ import annotations

from typing import Any, Iterable

from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    validate_character_definition,
)


HOST = "3dsmax"


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


def _control(name: str, target: Any, module: str, *, size: float = 5.0, parent: Any = None):
    rt = _rt()
    control = rt.getNodeByName(str(name))
    if control is None:
        control = rt.Point(
            name=str(name), size=max(float(size), 0.01), box=True,
            cross=False, centermarker=True, axistripod=False,
        )
    control.transform = target.transform
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
    ik_control = _control(f"{end.name}_ik_ctrl", end, module, size=float(payload.get("size", 5.0) or 5.0))
    pole_control = _control(f"{mid.name}_pole_ctrl", mid, module, size=float(payload.get("size", 5.0) or 5.0))
    pole_control.position = pole_control.position + rt.Point3(
        0, -max(float(getattr(start, "width", 10.0)), 10.0), 0
    )
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
    _set_tag(goal, "tc_ik_blend", float(payload.get("blend", 1.0)))
    _set_tag(ik_control, "tc_stretch", stretch)
    _set_tag(start, "tc_stretch", stretch)
    _set_tag(mid, "tc_stretch", stretch)
    return _result(True, "rig.create_ik_fk_limb", "Created native 3ds Max IK Limb controls.",
                   created_ids=[str(ik_control.name), str(pole_control.name), str(goal.name)],
                   data={"limb": module, "ik_control": str(ik_control.name),
                         "pole_control": str(pole_control.name), "goal": str(goal.name),
                         "stretch_control": str(ik_control.name), "stretch_attribute": "tc_stretch"})


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
    base_name = str(start.name)
    name = base_name[:-7] + "_twist_driver" if base_name.endswith("_driver") else base_name + "_twist_driver"
    twist_driver = _control(name, end, module, size=float(payload.get("size", 3.0) or 3.0), parent=start)
    _set_tag(twist_driver, "tc_twist_driver", True)
    twist_nodes = [_node(value) for value in payload.get("twist_joints") or []]
    created = [str(twist_driver.name)]
    count = len(twist_nodes)
    for index, twist in enumerate(twist_nodes, 1):
        weight = index / float(count + 1)
        _constrain(twist, "orient", [start, end], [(1.0 - weight) * 100.0, weight * 100.0])
        _set_tag(twist, "tc_rig_module", module)
        created.append(str(twist.name))
    return _result(True, "rig.create_twist", "Created 3ds Max twist distribution.", created_ids=created,
                   data={"twist_driver": str(twist_driver.name), "parent": str(start.name)})


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
    elif module in {"left_arm", "right_arm", "left_leg", "right_leg"} and len(targets) >= 3:
        result = _op_rig_create_ik_fk_limb({
            "start": targets[0][1], "mid": targets[1][1], "end": targets[2][1], "module": module,
            "stretch": payload.get("stretch", 1.0),
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
        for slot, target_name in targets:
            target = _node(target_name)
            control = _control(names.get(slot, f"{slot}_ctrl"), target, module)
            _constrain(target, "parent", [control], [100.0])
            controls.append(control)
            created.append(str(control.name))
        if module == "mouth":
            parent = _control("lip_main_ctrl", _node(targets[0][1]), module, size=7.5)
            for control in controls:
                world_transform = control.transform
                control.parent = parent
                control.transform = world_transform
            created.insert(0, str(parent.name))
    return _result(True, "rig.build_module", f"Built 3ds Max module {module}.",
                   created_ids=created, data={"module": module})


def _op_rig_build_full(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    modules = list(payload.get("modules") or (
        "root", "pelvis", "spine", "neck", "head", "left_arm", "right_arm", "left_leg", "right_leg"
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
        result = _op_rig_build_module({"module": module, "definition": definition.to_dict()})
        if result["ok"]:
            created.extend(result["created_ids"])
        else:
            warnings.append(f"{module}: {result['message']}")
    return _result(not warnings, "rig.build_full", f"Built {len(modules) - len(warnings)} 3ds Max rig modules.",
                   created_ids=created, warnings=warnings, data={"modules": modules})


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
