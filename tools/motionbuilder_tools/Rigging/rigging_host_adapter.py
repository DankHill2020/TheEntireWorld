"""MotionBuilder translation endpoint for the shared TC rigging workspace."""

from __future__ import annotations

import copy
from typing import Any

from pyfbsdk import (
    FBCharacter,
    FBConstraintManager,
    FBFindModelByLabelName,
    FBModelNull,
    FBModelSkeleton,
    FBPlotOptions,
    FBSystem,
)

from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    validate_character_definition,
)


HOST = "motionbuilder"
_definitions: dict[str, CharacterDefinition] = {}
_space_switches: dict[str, dict[str, Any]] = {}


def _result(ok: bool, capability: str, message: str = "", **kwargs: Any) -> dict[str, Any]:
    return RiggingOperationResult(ok, capability, HOST, message, **kwargs).to_dict()


def _model_name(model) -> str:
    return str(getattr(model, "LongName", "") or getattr(model, "Name", ""))


def scene_joints() -> dict[str, Any]:
    rows = []
    for component in FBSystem().Scene.Components:
        if not isinstance(component, FBModelSkeleton):
            continue
        parent = component.Parent if isinstance(component.Parent, FBModelSkeleton) else None
        depth, cursor, seen = 0, parent, set()
        while cursor is not None and id(cursor) not in seen:
            seen.add(id(cursor))
            depth += 1
            cursor = cursor.Parent if isinstance(cursor.Parent, FBModelSkeleton) else None
        matrix = component.GetMatrix()
        rows.append({
            "id": _model_name(component), "native_id": _model_name(component), "name": component.Name,
            "parent_id": _model_name(parent) if parent else "", "depth": depth,
            "world_matrix": [float(matrix[index]) for index in range(16)],
        })
    return _result(True, "host.query", data={"joints": rows})


def selection() -> dict[str, Any]:
    selected = [
        _model_name(component) for component in FBSystem().Scene.Components
        if bool(getattr(component, "Selected", False))
    ]
    return _result(True, "host.query", data={"selection": selected})


def execute(capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = globals().get("_op_" + str(capability).replace(".", "_"))
    if handler is None:
        return _result(False, capability, f"MotionBuilder cannot author this operation directly: {capability}",
                       warnings=["Build it in TC or Maya, then transfer/bake it to MotionBuilder."])
    try:
        return handler(dict(payload))
    except Exception as exc:
        return _result(False, capability, str(exc))


def _definition(value: Any) -> CharacterDefinition:
    if isinstance(value, CharacterDefinition):
        return value
    if isinstance(value, dict):
        if "schema" in value or "slots" in value:
            return CharacterDefinition.from_dict(value)
        return CharacterDefinition("Character", {str(key): str(node) for key, node in value.items() if node})
    key = str(value or "")
    if key in _definitions:
        return _definitions[key]
    raise ValueError("A portable character definition is required.")


def _op_definition_auto_map(payload: dict[str, Any]) -> dict[str, Any]:
    definition = auto_map_character(
        scene_joints()["data"]["joints"], name=str(payload.get("name") or "Character"),
        source_provider=HOST, source_root=str(payload.get("root_joint") or ""),
    )
    _definitions[definition.name] = definition
    validation = validate_character_definition(definition, scene_joints()["data"]["joints"])
    return _result(True, "definition.auto_map", f"Mapped {len(definition.slots)} MotionBuilder joints.",
                   data={"definition": definition.to_dict(), "validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_assign_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    joint = str(payload["joint"])
    if FBFindModelByLabelName(joint) is None:
        raise ValueError(f"MotionBuilder model does not exist: {joint}")
    definition.slots[str(payload["slot"])] = joint
    _definitions[definition.name] = definition
    return _result(True, "definition.assign_slot", "Assigned MotionBuilder character slot.", data={"definition": definition.to_dict()})


def _op_definition_clear_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.slots.pop(str(payload["slot"]), None)
    return _result(True, "definition.clear_slot", "Cleared MotionBuilder character slot.", data={"definition": definition.to_dict()})


def _op_definition_mirror_slots(payload: dict[str, Any]) -> dict[str, Any]:
    definition = mirror_character_slots(_definition(payload.get("definition")), str(payload.get("source_side") or "left"))
    _definitions[definition.name] = definition
    return _result(True, "definition.mirror_slots", "Mirrored MotionBuilder slot assignments.", data={"definition": definition.to_dict()})


def _op_definition_validate(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_character_definition(_definition(payload["mapping"]), scene_joints()["data"]["joints"])
    return _result(validation.ok, "definition.validate", "Definition is valid." if validation.ok else "Definition needs attention.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_set_reference_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.reference_pose = {}
    for model_name in set(definition.slots.values()):
        model = FBFindModelByLabelName(model_name)
        if model is not None:
            matrix = model.GetMatrix()
            definition.reference_pose[model_name] = [float(matrix[index]) for index in range(16)]
    return _result(True, "definition.set_reference_pose", "Captured MotionBuilder reference pose.",
                   changed_ids=list(definition.reference_pose), data={"definition": definition.to_dict()})


def _op_definition_import(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    _definitions[definition.name] = definition
    return _result(True, "definition.import", f"Imported {definition.name}.", data={"definition": definition.to_dict()})


def _op_definition_export(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.export", f"Prepared {definition.name} for export.", data={"definition": definition.to_dict()})


_op_retarget_create_definition = _op_definition_import
_op_retarget_validate_definition = _op_definition_validate


def _op_rig_create_control(payload: dict[str, Any]) -> dict[str, Any]:
    target = FBFindModelByLabelName(str(payload["target"]))
    if target is None:
        raise ValueError("Control target was not found.")
    name = str(payload.get("name") or target.Name + "_ctrl")
    control = FBModelNull(name)
    control.Show = True
    control.SetMatrix(target.GetMatrix())
    parent_name = str(payload.get("parent") or "")
    if parent_name:
        parent = FBFindModelByLabelName(parent_name)
        if parent is not None:
            control.Parent = parent
    return _result(True, "rig.create_control", f"Created MotionBuilder control {name}.", created_ids=[_model_name(control)])


def _constraint_type_name(kind: str) -> str:
    return {
        "parent": "Parent/Child", "point": "Position", "orient": "Rotation",
        "rotate": "Rotation", "scale": "Scale", "aim": "Aim",
    }.get(str(kind).lower(), str(kind))


def _op_rig_create_constraint(payload: dict[str, Any]) -> dict[str, Any]:
    manager = FBConstraintManager()
    type_name = _constraint_type_name(payload["type"])
    type_index = next((index for index in range(manager.TypeGetCount()) if manager.TypeGetName(index) == type_name), -1)
    if type_index < 0:
        raise ValueError(f"MotionBuilder constraint type is unavailable: {type_name}")
    constraint = manager.TypeCreateConstraint(type_index)
    constraint.Name = str(payload.get("name") or f"TC_{type_name}_Constraint")
    for driver in payload["drivers"]:
        model = FBFindModelByLabelName(str(driver))
        if model is not None:
            constraint.ReferenceAdd(0, model)
    driven = FBFindModelByLabelName(str(payload["driven"]))
    if driven is None:
        raise ValueError("Driven model was not found.")
    constraint.ReferenceAdd(1, driven)
    constraint.Snap()
    constraint.Active = True
    return _result(True, "rig.create_constraint", f"Created MotionBuilder {type_name} constraint.", created_ids=[constraint.Name])


def _op_rig_create_ik_fk_limb(payload: dict[str, Any]) -> dict[str, Any]:
    created = []
    for role, target_name in (("ik", payload["end"]), ("pole", payload.get("pole_target") or payload["mid"])):
        target = FBFindModelByLabelName(str(target_name))
        if target is None:
            continue
        control = FBModelNull(str(payload.get("module") or "limb") + "_" + role + "_ctrl")
        control.Show = True
        control.SetMatrix(target.GetMatrix())
        created.append(_model_name(control))
    return _result(True, "rig.create_ik_fk_limb", "Created MotionBuilder limb controls.", created_ids=created,
                   warnings=["MotionBuilder's solver/control-rig characterization remains authoritative for the live solve."])


def _op_rig_set_ik_fk_blend(payload: dict[str, Any]) -> dict[str, Any]:
    character = next((item for item in FBSystem().Scene.Characters if item.Name == str(payload["limb"])), None)
    if character is None:
        raise ValueError("MotionBuilder character was not found.")
    character.ActiveInput = float(payload["blend"]) >= 0.5
    return _result(True, "rig.set_ik_fk_blend", "Updated MotionBuilder character input blend.", changed_ids=[character.Name])


def _op_rig_create_space_switch(payload: dict[str, Any]) -> dict[str, Any]:
    switch_id = str(payload.get("name") or str(payload["driven"]) + "_space")
    _space_switches[switch_id] = {
        "driven": str(payload["driven"]), "targets": [str(value) for value in payload["targets"]],
        "active": int(payload.get("active", 0) or 0), "mode": str(payload.get("mode") or "parent"),
    }
    result = _activate_space(switch_id)
    result["capability"] = "rig.create_space_switch"
    result["data"] = {"space_switch": switch_id}
    return result


def _op_rig_set_space(payload: dict[str, Any]) -> dict[str, Any]:
    switch_id = str(payload["space_switch"])
    if switch_id not in _space_switches:
        raise ValueError("MotionBuilder space switch was not found in this UI session.")
    _space_switches[switch_id]["active"] = int(payload["space"])
    return _activate_space(switch_id)


def _activate_space(switch_id: str) -> dict[str, Any]:
    state = _space_switches[switch_id]
    targets = state["targets"]
    active = int(state["active"])
    if active < 0 or active >= len(targets):
        raise IndexError("Space index is outside the target range.")
    return _op_rig_create_constraint({
        "type": state["mode"], "drivers": [targets[active]], "driven": state["driven"],
        "name": switch_id + "_constraint",
    })


def _op_rig_create_motion_path(payload: dict[str, Any]) -> dict[str, Any]:
    return _result(False, "rig.create_motion_path", "MotionBuilder path authoring requires a Path constraint route.")


def _op_rig_store_connections(payload: dict[str, Any]) -> dict[str, Any]:
    constraints = [component.Name for component in FBSystem().Scene.Constraints]
    return _result(True, "rig.store_connections", "Captured MotionBuilder constraints.", data={"constraints": constraints})


def _op_rig_restore_connections(payload: dict[str, Any]) -> dict[str, Any]:
    return _result(True, "rig.restore_connections", "Portable connection metadata loaded; live constraints are recreated per operation.")


def _op_retarget_solve_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    changed = []
    for slot, matrix_values in dict(payload["source"]).items():
        model = FBFindModelByLabelName(definition.slots.get(slot, ""))
        if model is None or not isinstance(matrix_values, (list, tuple)) or len(matrix_values) != 16:
            continue
        matrix = model.GetMatrix()
        for index, value in enumerate(matrix_values):
            matrix[index] = float(value)
        model.SetMatrix(matrix)
        changed.append(_model_name(model))
    return _result(True, "retarget.solve_pose", f"Solved {len(changed)} MotionBuilder joints.", changed_ids=changed)


_op_retarget_preview = _op_retarget_solve_pose


def _op_retarget_bake(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    options = FBPlotOptions()
    plotted = []
    for model_name in set(definition.slots.values()):
        model = FBFindModelByLabelName(model_name)
        if model is not None and model.AnimationNode is not None:
            model.PlotAnimation(options)
            plotted.append(model_name)
    return _result(True, "retarget.bake", f"Plotted {len(plotted)} MotionBuilder models.", changed_ids=plotted)


def _op_retarget_transfer_take(payload: dict[str, Any]) -> dict[str, Any]:
    return _result(True, "retarget.transfer_take", "Take metadata accepted by MotionBuilder.", data={"take": copy.deepcopy(payload["take"])})
