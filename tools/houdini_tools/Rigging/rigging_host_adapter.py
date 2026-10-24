"""Houdini/KineFX translation endpoint for the shared rigging workspace.

The adapter uses ordinary OBJ nodes for animator controls and stores portable
solver descriptions on a dedicated subnet.  KineFX skeleton points are also
reported by :func:`scene_joints`, so definitions can target either object bones
or SOP skeleton geometry.
"""

from __future__ import annotations

import json
import importlib
from typing import Any

from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    twist_driver_contract,
    validate_character_definition,
)


HOST = "houdini"
RIG_BEHAVIOR_REVISION = 2


def _hou():
    import hou

    return hou


def _result(ok: bool, capability: str, message: str = "", **kwargs: Any) -> dict[str, Any]:
    return RiggingOperationResult(ok, capability, HOST, message, **kwargs).to_dict()


def _workspace():
    hou = _hou()
    root = hou.node("/obj")
    node = root.node("TC_RiggingWorkspace")
    if node is None:
        node = root.createNode("subnet", "TC_RiggingWorkspace")
        node.setUserData("tc_rigging_workspace", "1")
    return node


def _state() -> dict[str, Any]:
    raw = _workspace().userData("tc_rigging_state") or "{}"
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    _workspace().setUserData("tc_rigging_state", json.dumps(state, default=str, sort_keys=True))


def _node(value: str):
    hou = _hou()
    node = hou.node(str(value))
    if node is None:
        matches = hou.node("/obj").glob(str(value))
        node = matches[0] if len(matches) == 1 else None
    if node is None:
        raise ValueError(f"Houdini node does not exist: {value}")
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
    return [float(value) for value in matrix.asTuple()]


def _matrix(values: Any):
    data = [float(value) for value in values]
    if len(data) != 16:
        raise ValueError("A transform matrix requires 16 values")
    return _hou().Matrix4(tuple(data))


def _control(name: str, target: str = "", module: str = "custom"):
    parent = _workspace()
    control = parent.node(name)
    if control is None:
        control = parent.createNode("null", name)
    control.setUserData("tc_rig_module", module)
    control.setUserData("tc_control", "1")
    if target:
        target_node = _node(target)
        control.setWorldTransform(target_node.worldTransform())
        control.setUserData("tc_target", target_node.path())
    return control


def _record(kind: str, payload: dict[str, Any], *, record_id: str = "") -> str:
    state = _state()
    records = state.setdefault("records", {})
    record_id = record_id or f"{kind}_{len(records) + 1:04d}"
    records[record_id] = {"kind": kind, "payload": payload}
    _save_state(state)
    return record_id


def reload_dependencies() -> int:
    """Refresh the shared portable contract used by this live Houdini host."""
    global CharacterDefinition, RiggingOperationResult
    global auto_map_character, mirror_character_slots, twist_driver_contract
    global validate_character_definition
    contract = importlib.reload(importlib.import_module(
        "tech_connector.services.dcc.rigging_workspace_service"
    ))
    for name in (
        "CharacterDefinition", "RiggingOperationResult", "auto_map_character",
        "mirror_character_slots", "twist_driver_contract", "validate_character_definition",
    ):
        globals()[name] = getattr(contract, name)
    return RIG_BEHAVIOR_REVISION


def scene_joints() -> dict[str, Any]:
    hou = _hou()
    rows = []
    for node in hou.node("/obj").allSubChildren():
        if node.type().name() not in {"bone", "null"} or node.userData("tc_control") == "1":
            continue
        parent = node.input(0) or node.parent()
        rows.append({
            "id": node.path(), "native_id": str(node.sessionId()), "name": node.name(),
            "parent_id": parent.path() if parent and parent.path() != "/obj" else "",
            "depth": node.path().count("/") - 2,
            "local_matrix": _matrix_values(node.localTransform()),
            "world_matrix": _matrix_values(node.worldTransform()),
        })
    for sop in hou.node("/obj").allSubChildren():
        if sop.type().category() != hou.sopNodeTypeCategory():
            continue
        try:
            geometry = sop.geometry()
            name_attr = geometry.findPointAttrib("name")
        except hou.Error:
            continue
        if name_attr is None:
            continue
        for point in geometry.points():
            name = str(point.attribValue(name_attr))
            transform = point.attribValue("transform") if geometry.findPointAttrib("transform") else None
            matrix = hou.Matrix4(transform) if transform and len(transform) == 16 else hou.hmath.buildTranslate(point.position())
            rows.append({
                "id": f"{sop.path()}:{name}", "native_id": str(point.number()), "name": name,
                "parent_id": "", "depth": 0, "local_matrix": _matrix_values(matrix),
                "world_matrix": _matrix_values(matrix * sop.parent().worldTransform()),
            })
    return _result(True, "host.query", data={"joints": rows})


def selection() -> dict[str, Any]:
    return _result(True, "host.query", data={"selection": [node.path() for node in _hou().selectedNodes()]})


def execute(capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = globals().get("_op_" + str(capability).replace(".", "_"))
    if handler is None:
        return _result(False, capability, f"Houdini translation is not implemented: {capability}")
    hou = _hou()
    try:
        with hou.undos.group(f"Tech Connector: {capability}"):
            return handler(dict(payload))
    except Exception as exc:
        return _result(False, capability, str(exc))


def _op_definition_auto_map(payload: dict[str, Any]) -> dict[str, Any]:
    rows = scene_joints()["data"]["joints"]
    definition = auto_map_character(rows, name=str(payload.get("name") or "Character"),
                                    source_provider=HOST, source_root=str(payload.get("root_joint") or ""))
    validation = validate_character_definition(definition, rows)
    return _result(True, "definition.auto_map", f"Mapped {len(definition.slots)} Houdini joints.",
                   data={"definition": definition.to_dict(), "validation": validation.to_dict()},
                   warnings=validation.warnings)


def _op_definition_assign_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    definition.slots[str(payload["slot"])] = str(payload["joint"])
    return _result(True, "definition.assign_slot", "Assigned Houdini character slot.", data={"definition": definition.to_dict()})


def _op_definition_clear_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    definition.slots.pop(str(payload["slot"]), None)
    return _result(True, "definition.clear_slot", "Cleared Houdini character slot.", data={"definition": definition.to_dict()})


def _op_definition_mirror_slots(payload: dict[str, Any]) -> dict[str, Any]:
    direction = str(payload.get("direction") or payload.get("source_side") or "left").lower()
    source_side = "right" if direction.startswith("right") else "left"
    definition = mirror_character_slots(_definition(payload["definition"]), source_side)
    return _result(True, "definition.mirror_slots", "Mirrored Houdini character slots.", data={"definition": definition.to_dict()})


def _op_definition_validate(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_character_definition(_definition(payload["definition"]), scene_joints()["data"]["joints"])
    return _result(validation.ok, "definition.validate", "Validated Houdini definition.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_set_reference_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    definition.reference_pose = {row["id"]: row["world_matrix"] for row in scene_joints()["data"]["joints"]
                                 if row["id"] in definition.slots.values()}
    return _result(True, "definition.set_reference_pose", "Captured Houdini reference pose.", data={"definition": definition.to_dict()})


def _op_definition_import(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition") or payload.get("data"))
    return _result(True, "definition.import", "Imported Houdini definition.", data={"definition": definition.to_dict()})


def _op_definition_export(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.export", "Exported Houdini definition.", data={"definition": definition.to_dict()})


def _op_rig_create_control(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload["target"])
    control = _control(str(payload.get("name") or f"{target.rsplit('/', 1)[-1]}_ctrl"), target,
                       str(payload.get("module") or "custom"))
    return _result(True, "rig.create_control", "Created Houdini control.", created_ids=[control.path()])


def _op_rig_edit_control_shape(payload: dict[str, Any]) -> dict[str, Any]:
    control = _node(payload["control"])
    control.setUserData("tc_control_shape", str(payload.get("shape") or ""))
    control.setUserData("tc_control_cv_positions", json.dumps(payload.get("cv_positions") or []))
    return _result(True, "rig.edit_control_shape", "Updated Houdini control shape.", changed_ids=[control.path()])


def _op_rig_create_constraint(payload: dict[str, Any]) -> dict[str, Any]:
    driven = _node(payload["driven"])
    drivers = [_node(value) for value in payload["drivers"]]
    kind = str(payload["type"]).lower()
    if kind == "parent" and len(drivers) == 1:
        world = driven.worldTransform()
        driven.setInput(0, drivers[0])
        if bool(payload.get("offset", True)):
            driven.setWorldTransform(world)
    record = _record("constraint", {**payload, "driven": driven.path(), "drivers": [node.path() for node in drivers]})
    return _result(True, "rig.create_constraint", f"Created Houdini {kind} constraint.", created_ids=[record])


def _op_rig_create_ik_fk_limb(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload.get("module") or f"{str(payload['end']).rsplit('/', 1)[-1]}_limb")
    created = []
    parent = None
    for role in ("start", "mid", "end"):
        control = _control(f"{module}_{role}_fk_ctrl", str(payload[role]), module)
        if parent is not None:
            control.setInput(0, parent)
        parent = control
        created.append(control.path())
    for role, target in (("ik", payload["end"]), ("pole", payload["mid"])):
        created.append(_control(f"{module}_{role}_ctrl", str(target), module).path())
    created.append(_record("ik_fk_limb", payload, record_id=f"{module}_solver"))
    return _result(True, "rig.create_ik_fk_limb", "Created Houdini IK/FK limb controls.", created_ids=created,
                   data={"module": module, "behavior_revision": RIG_BEHAVIOR_REVISION})


def _op_rig_set_ik_fk_blend(payload: dict[str, Any]) -> dict[str, Any]:
    record = _record("ik_fk_blend", payload, record_id=f"{payload['limb']}_blend")
    return _result(True, "rig.set_ik_fk_blend", "Updated Houdini IK/FK blend.", changed_ids=[record])


def _op_rig_create_reverse_foot(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload.get("module") or f"{str(payload['ankle']).rsplit('/', 1)[-1]}_reverse_foot")
    created, parent = [], None
    for role, target in (("heel", payload["ankle"]), ("toe", payload["toe"]),
                         ("ball", payload["ball"]), ("ankle", payload["ankle"])):
        control = _control(f"{module}_{role}_pivot", str(target), module)
        if parent is not None:
            control.setInput(0, parent)
        parent = control
        created.append(control.path())
    return _result(True, "rig.create_reverse_foot", "Created Houdini reverse-foot pivots.", created_ids=created)


def _op_rig_create_ribbon(payload: dict[str, Any]) -> dict[str, Any]:
    record = _record("kinefx_ribbon", payload)
    return _result(True, "rig.create_ribbon", "Created Houdini KineFX ribbon description.", created_ids=[record])


def _op_rig_create_twist(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload.get("module") or f"{payload['start']}_twist")
    settings = twist_driver_contract(
        str(payload["start"]),
        parent=str(payload.get("parent") or payload["start"]),
        module=module,
        overrides=payload,
    )
    record = _record("kinefx_twist", {**payload, "constraint_settings": settings})
    return _result(
        True,
        "rig.create_twist",
        "Created Houdini KineFX twist distribution.",
        created_ids=[record],
        data={"constraint_settings": settings, "behavior_revision": RIG_BEHAVIOR_REVISION},
    )


def _op_rig_create_motion_path(payload: dict[str, Any]) -> dict[str, Any]:
    record = _record("motion_path", payload)
    return _result(True, "rig.create_motion_path", "Created Houdini motion-path solver.", created_ids=[record])


def _op_rig_create_curve_joints(payload: dict[str, Any]) -> dict[str, Any]:
    record = _record("curve_joints", payload)
    return _result(True, "rig.create_curve_joints", "Created Houdini curve-joint recipe.", created_ids=[record])


def _op_rig_create_space_switch(payload: dict[str, Any]) -> dict[str, Any]:
    switch_id = str(payload.get("name") or f"{str(payload['driven']).rsplit('/', 1)[-1]}_space")
    record = _record("space_switch", {**payload, "active": int(payload.get("active", 0) or 0)}, record_id=switch_id)
    return _result(True, "rig.create_space_switch", "Created Houdini space switch.", created_ids=[record], data={"space_switch": record})


def _op_rig_set_space(payload: dict[str, Any]) -> dict[str, Any]:
    state = _state()
    switch_id = str(payload["space_switch"])
    record = state.get("records", {}).get(switch_id)
    if record is None:
        raise KeyError(f"Unknown Houdini space switch: {switch_id}")
    record["payload"]["active"] = payload["space"]
    _save_state(state)
    return _result(True, "rig.set_space", "Updated Houdini active space.", changed_ids=[switch_id])


def _op_rig_create_mesh_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    record = _record("kinefx_mesh_attachment", payload)
    return _result(True, "rig.create_mesh_attachment", "Created Houdini mesh attachment.", created_ids=[record])


def _op_rig_create_pose_reader(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or f"{str(payload['driver']).rsplit('/', 1)[-1]}_pose_reader")
    reader = _control(name, str(payload["driver"]), str(payload.get("module") or "pose_reader"))
    reader.setUserData("tc_pose_reader", json.dumps(payload, default=str))
    return _result(True, "rig.create_pose_reader", "Created Houdini pose reader.", created_ids=[reader.path()])


def _op_rig_build_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    definition = _definition(payload["definition"])
    created = []
    for slot, target in definition.slots.items():
        if module not in slot.lower() and not (module == "spine" and slot.lower() in {"hips", "spine", "chest"}):
            continue
        try:
            created.append(_control(f"{slot}_ctrl", target, module).path())
        except ValueError:
            continue
    _record("module", payload, record_id=f"module_{module}")
    return _result(True, "rig.build_module", f"Built Houdini module {module}.", created_ids=created)


def _op_rig_remove_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    removed = []
    workspace = _workspace()
    for node in list(workspace.children()):
        if str(node.userData("tc_rig_module") or "").lower() == module:
            removed.append(node.path())
            node.destroy()
    state = _state()
    for key in list(state.get("records", {})):
        data = state["records"][key].get("payload", {})
        if str(data.get("module") or "").lower() == module or key == f"module_{module}":
            state["records"].pop(key, None)
            removed.append(key)
    _save_state(state)
    return _result(True, "rig.remove_module", f"Removed Houdini module {module}.", removed_ids=removed)


def _op_rig_rebuild_module(payload: dict[str, Any]) -> dict[str, Any]:
    removed = _op_rig_remove_module(payload)
    built = _op_rig_build_module(payload)
    built["capability"] = "rig.rebuild_module"
    built["removed_ids"] = removed["removed_ids"]
    return built


def _op_rig_build_full(payload: dict[str, Any]) -> dict[str, Any]:
    modules = list(payload.get("modules") or ("root", "spine", "neck", "head", "left_arm", "right_arm", "left_leg", "right_leg"))
    created, warnings = [], []
    for module in modules:
        result = _op_rig_build_module({**payload, "module": module})
        created.extend(result.get("created_ids") or [])
        warnings.extend(result.get("warnings") or [])
    return _result(True, "rig.build_full", f"Built {len(modules)} Houdini rig modules.", created_ids=created,
                   warnings=warnings, data={"modules": modules, "behavior_revision": RIG_BEHAVIOR_REVISION})


def _op_rig_place_joints(payload: dict[str, Any]) -> dict[str, Any]:
    positions = dict(payload.get("positions") or payload.get("world_positions") or {})
    definition = _definition(payload["definition"])
    changed = []
    for slot, position in positions.items():
        target = definition.slots.get(slot, slot)
        try:
            node = _node(target)
        except ValueError:
            continue
        transform = node.worldTransform()
        transform.setAt(3, 0, float(position[0])); transform.setAt(3, 1, float(position[1])); transform.setAt(3, 2, float(position[2]))
        node.setWorldTransform(transform)
        changed.append(node.path())
    return _result(True, "rig.place_joints", f"Placed {len(changed)} Houdini joints.", changed_ids=changed)


def _op_rig_set_t_pose(payload: dict[str, Any]) -> dict[str, Any]:
    record = _record("t_pose", payload, record_id="t_pose")
    return _result(True, "rig.set_t_pose", "Stored Houdini T-pose operation.", changed_ids=[record])


def _op_rig_create_face_module(payload: dict[str, Any]) -> dict[str, Any]:
    return _op_rig_build_module({**payload, "module": str(payload.get("module") or "face")})


def _op_rig_store_connections(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"])
    state = _state()
    connections = {key: value for key, value in state.get("records", {}).items()
                   if str(value.get("payload", {}).get("module") or "") == module}
    state.setdefault("connection_snapshots", {})[module] = connections
    _save_state(state)
    return _result(True, "rig.store_connections", f"Stored {len(connections)} Houdini module connections.",
                   data={"connections": connections})


def _op_rig_restore_connections(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"])
    state = _state()
    connections = state.get("connection_snapshots", {}).get(module, {})
    state.setdefault("records", {}).update(connections)
    _save_state(state)
    return _result(True, "rig.restore_connections", f"Restored {len(connections)} Houdini module connections.",
                   changed_ids=list(connections), data={"connections": connections})


def _op_skin_surface_spatial_smooth_brush(payload: dict[str, Any]) -> dict[str, Any]:
    state = _state()
    state["active_skin_brush"] = {"type": "surface_spatial_smooth", **payload}
    _save_state(state)
    return _result(True, "skin.surface_spatial_smooth_brush", "Configured Houdini surface-spatial skin brush.", data=payload)


def _op_retarget_create_definition(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["mapping"])
    return _result(True, "retarget.create_definition", "Created Houdini retarget definition.", data={"definition": definition.to_dict()})


def _op_retarget_validate_definition(payload: dict[str, Any]) -> dict[str, Any]:
    result = _op_definition_validate(payload)
    result["capability"] = "retarget.validate_definition"
    return result


def _op_retarget_solve_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    changed = []
    for slot, values in dict(payload["source"]).items():
        target = definition.slots.get(slot)
        if not target or not isinstance(values, (list, tuple)) or len(values) != 16:
            continue
        try:
            node = _node(target)
        except ValueError:
            continue
        node.setWorldTransform(_matrix(values))
        changed.append(node.path())
    return _result(True, "retarget.solve_pose", f"Solved {len(changed)} Houdini joints.", changed_ids=changed)


def _op_retarget_preview(payload: dict[str, Any]) -> dict[str, Any]:
    result = _op_retarget_solve_pose(payload)
    result["capability"] = "retarget.preview"
    return result


def _op_retarget_bake(payload: dict[str, Any]) -> dict[str, Any]:
    hou = _hou()
    definition = _definition(payload["target"])
    start, end = (int(round(float(value))) for value in payload["range"])
    step = max(1, int(round(float(payload.get("sample_rate", 1) or 1))))
    changed = []
    for target in definition.slots.values():
        try:
            node = _node(target)
        except ValueError:
            continue
        for parm_name in ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"):
            parm = node.parm(parm_name)
            if parm is None:
                continue
            for frame in range(start, end + 1, step):
                parm.setKeyframe(hou.Keyframe(parm.evalAtFrame(frame), frame))
        changed.append(node.path())
    return _result(True, "retarget.bake", "Baked retargeted Houdini animation.", changed_ids=changed)


def _op_retarget_transfer_take(payload: dict[str, Any]) -> dict[str, Any]:
    state = _state()
    state["retarget_take"] = payload["take"]
    _save_state(state)
    return _result(True, "retarget.transfer_take", "Stored Houdini retarget take metadata.", data={"take": payload["take"]})
