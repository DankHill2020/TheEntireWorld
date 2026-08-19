"""Tech Connector-native implementation of the shared rigging workspace API."""

from __future__ import annotations

import copy
import math
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.game_engine.authoring.rig_evaluation_service import (
    calculate_constraint_offset_matrix,
    evaluate_rig_graph,
)
from tech_connector.game_engine.authoring.rigging_workspace_service import (
    CharacterDefinition,
    FINGER_SLOTS,
    RIGGING_CAPABILITIES,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    validate_character_definition,
)


def _stable_ribbon_grid(
    positions: list[list[float]],
    *,
    width: float,
    up_vector: tuple[float, float, float],
) -> list[list[list[float]]]:
    points = [[float(value) for value in point[:3]] for point in positions]
    if len(points) < 2:
        raise ValueError("A ribbon requires at least two positions.")

    def subtract(first, second):
        return [first[index] - second[index] for index in range(3)]

    def dot(first, second):
        return sum(first[index] * second[index] for index in range(3))

    def cross(first, second):
        return [
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        ]

    def normalize(value):
        length = math.sqrt(max(0.0, dot(value, value)))
        if length <= 1.0e-8:
            raise ValueError("Ribbon chain contains coincident points.")
        return [component / length for component in value]

    tangents = []
    for index in range(len(points)):
        if index == 0:
            tangent = subtract(points[1], points[0])
        elif index == len(points) - 1:
            tangent = subtract(points[-1], points[-2])
        else:
            tangent = subtract(points[index + 1], points[index - 1])
        tangents.append(normalize(tangent))

    preferred = normalize(list(up_vector))
    side = cross(preferred, tangents[0])
    if math.sqrt(dot(side, side)) <= 1.0e-8:
        fallback = min(
            ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]),
            key=lambda axis: abs(dot(axis, tangents[0])),
        )
        side = cross(fallback, tangents[0])
    side = normalize(side)
    sides = [side]
    for tangent in tangents[1:]:
        previous = sides[-1]
        transported = [previous[index] - tangent[index] * dot(previous, tangent) for index in range(3)]
        if math.sqrt(dot(transported, transported)) <= 1.0e-8:
            transported = cross(preferred, tangent)
        transported = normalize(transported)
        if dot(transported, previous) < 0.0:
            transported = [-value for value in transported]
        sides.append(transported)

    return [
        [
            [point[index] - side[index] * width for index in range(3)],
            [point[index] + side[index] * width for index in range(3)],
        ]
        for point, side in zip(points, sides)
    ]


TC_NATIVE_CAPABILITY_STATUS = {
    key: "native" for key in RIGGING_CAPABILITIES
}
TC_NATIVE_CAPABILITY_STATUS.update({
    "rig.create_mesh_attachment": "bake",
})


class TCRiggingHostAdapter:
    """Execute portable rigging operations against an EditableRigGraph."""

    def __init__(self, graph: EditableRigGraph | None = None, selected_ids: list[str] | tuple[str, ...] | None = None):
        self.graph = graph or EditableRigGraph()
        self.definitions: dict[str, CharacterDefinition] = {}
        self.selected_ids = [str(value) for value in (selected_ids or [])]

    @property
    def host_id(self) -> str:
        return "tech_connector"

    def capabilities(self) -> dict[str, str]:
        return dict(TC_NATIVE_CAPABILITY_STATUS)

    def scene_joints(self) -> list[dict[str, Any]]:
        depths = {joint_id: self._joint_depth(joint_id) for joint_id in self.graph.joints}
        return [
            {
                **copy.deepcopy(joint),
                "native_id": joint_id,
                "depth": depths[joint_id],
                "world_matrix": self._joint_world_matrix(joint_id),
            }
            for joint_id, joint in self.graph.joints.items()
        ]

    def selection(self) -> list[str]:
        return [value for value in self.selected_ids if value in self.graph.nodes or value in self.graph.joints]

    def execute(self, capability: str, payload: dict[str, Any]) -> RiggingOperationResult:
        handler_name = "_op_" + capability.replace(".", "_")
        handler = getattr(self, handler_name, None)
        if handler is None:
            return RiggingOperationResult(
                False, capability, self.host_id, f"TC-native handler is not implemented: {capability}"
            )
        try:
            return handler(dict(payload))
        except Exception as exc:
            return RiggingOperationResult(False, capability, self.host_id, str(exc))

    def _ok(self, capability: str, message: str, **kwargs: Any) -> RiggingOperationResult:
        return RiggingOperationResult(True, capability, self.host_id, message, **kwargs)

    def _definition(self, value: Any) -> CharacterDefinition:
        if isinstance(value, CharacterDefinition):
            return value
        if isinstance(value, dict):
            return CharacterDefinition.from_dict(value)
        key = str(value or "")
        if key in self.definitions:
            return self.definitions[key]
        raise KeyError(f"Unknown character definition: {key}")

    def _op_definition_auto_map(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = auto_map_character(
            self.scene_joints(),
            name=str(payload.get("name") or "Character"),
            source_root=str(payload.get("root_joint") or ""),
        )
        self.definitions[definition.name] = definition
        validation = validate_character_definition(definition, self.scene_joints())
        return self._ok(
            "definition.auto_map", f"Mapped {len(definition.slots)} character slots.",
            data={"definition": definition.to_dict(), "validation": validation.to_dict()},
            warnings=list(validation.warnings),
        )

    def _op_definition_assign_slot(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload.get("definition"))
        slot, joint = str(payload["slot"]), str(payload["joint"])
        if joint not in self.graph.joints:
            raise KeyError(f"Unknown joint: {joint}")
        definition.slots[slot] = joint
        self.definitions[definition.name] = definition
        return self._ok("definition.assign_slot", f"Assigned {joint} to {slot}.", changed_ids=[joint])

    def _op_definition_clear_slot(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload.get("definition"))
        definition.slots.pop(str(payload["slot"]), None)
        return self._ok("definition.clear_slot", f"Cleared {payload['slot']}.")

    def _op_definition_mirror_slots(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = mirror_character_slots(
            self._definition(payload.get("definition")), str(payload.get("source_side") or "left")
        )
        self.definitions[definition.name] = definition
        return self._ok("definition.mirror_slots", "Mirrored character slot assignments.", data={"definition": definition.to_dict()})

    def _op_definition_validate(self, payload: dict[str, Any]) -> RiggingOperationResult:
        validation = validate_character_definition(self._definition(payload["mapping"]), self.scene_joints())
        return RiggingOperationResult(
            validation.ok, "definition.validate", self.host_id,
            "Character definition is valid." if validation.ok else "Character definition needs attention.",
            data={"validation": validation.to_dict()}, warnings=list(validation.warnings),
        )

    def _op_definition_set_reference_pose(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload.get("definition"))
        definition.reference_pose = {
            joint_id: self._joint_world_matrix(joint_id) for joint_id in set(definition.slots.values())
        }
        return self._ok(
            "definition.set_reference_pose",
            "Captured the TC reference pose.",
            changed_ids=list(definition.reference_pose),
            data={"definition": definition.to_dict()},
        )

    def _op_definition_import(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload["definition"])
        self.definitions[definition.name] = definition
        return self._ok("definition.import", f"Imported {definition.name}.", data={"definition": definition.to_dict()})

    def _op_definition_export(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload.get("definition") or next(iter(self.definitions), ""))
        return self._ok("definition.export", f"Prepared {definition.name} for export.", data={"definition": definition.to_dict()})

    def _op_retarget_create_definition(self, payload: dict[str, Any]) -> RiggingOperationResult:
        source = payload["mapping"]
        if isinstance(source, CharacterDefinition):
            definition = source
        elif isinstance(source, dict) and "schema" in source:
            definition = CharacterDefinition.from_dict(source)
        else:
            definition = CharacterDefinition(
                name=str(payload.get("name") or "Character"),
                slots={str(key): str(value) for key, value in dict(source).items() if value},
            )
        self.definitions[definition.name] = definition
        validation = validate_character_definition(definition, self.scene_joints())
        return RiggingOperationResult(
            validation.ok, "retarget.create_definition", self.host_id,
            "Created retarget definition." if validation.ok else "Created an incomplete retarget definition.",
            data={"definition": definition.to_dict(), "validation": validation.to_dict()},
            warnings=list(validation.warnings),
        )

    def _op_retarget_validate_definition(self, payload: dict[str, Any]) -> RiggingOperationResult:
        validation = validate_character_definition(self._definition(payload["definition"]), self.scene_joints())
        return RiggingOperationResult(validation.ok, "retarget.validate_definition", self.host_id,
                                      "Retarget definition is valid." if validation.ok else "Retarget definition is invalid.",
                                      data={"validation": validation.to_dict()})

    def _op_rig_create_control(self, payload: dict[str, Any]) -> RiggingOperationResult:
        target = str(payload["target"])
        if target not in self.graph.nodes:
            raise KeyError(f"Unknown control target: {target}")
        node_id = str(payload.get("control_id") or f"{target}_ctrl")
        if node_id in self.graph.nodes:
            raise ValueError(f"Control already exists: {node_id}")
        matrix = self._node_world_matrix(target)
        control = self.graph.add_node(
            str(payload.get("name") or node_id), "dag.control",
            parent_id=str(payload.get("parent") or ""), node_id=node_id,
            attributes={
                "matrix": matrix,
                "control_shape": str(payload.get("shape") or "circle"),
                "control_size": float(payload.get("size", 1.0) or 1.0),
                "rig_module": str(payload.get("module") or "custom"),
            },
        )
        if bool(payload.get("constrain", True)):
            self.graph.add_constraint(
                "parent", [control], target,
                settings={
                    "maintain_offset": True,
                    "rig_module": str(payload.get("module") or "custom"),
                },
            )
        return self._ok("rig.create_control", f"Created control {node_id}.", created_ids=[node_id])

    def _op_rig_edit_control_shape(self, payload: dict[str, Any]) -> RiggingOperationResult:
        control = str(payload["control"])
        node = self.graph.nodes.get(control)
        if node is None:
            raise KeyError(f"Unknown control: {control}")
        attrs = node.setdefault("attributes", {})
        if "shape" in payload:
            attrs["control_shape"] = str(payload["shape"])
        if "cv_positions" in payload:
            attrs["control_cv_positions"] = copy.deepcopy(payload["cv_positions"])
        return self._ok("rig.edit_control_shape", f"Updated {control}.", changed_ids=[control])

    def _op_rig_create_constraint(self, payload: dict[str, Any]) -> RiggingOperationResult:
        kind = str(payload["type"]).lower()
        driven = str(payload["driven"])
        maintain_offset = bool(payload.get("offset", True))
        current_world_matrix = None
        if maintain_offset:
            current_world_matrix = evaluate_rig_graph(self.graph).world_matrices.get(driven)
            if current_world_matrix is None:
                raise ValueError(f"Cannot calculate an offset for unavailable driven node: {driven}")
        settings = {
            "maintain_offset": maintain_offset,
            "axes": list(payload.get("axes") or ("x", "y", "z")),
            "weights": payload.get("weights"),
            "rig_module": str(payload.get("module") or "custom"),
            "aim_vector": list(payload.get("aim_vector") or payload.get("aimVector") or (1.0, 0.0, 0.0)),
            "up_vector": list(payload.get("up_vector") or payload.get("upVector") or (0.0, 1.0, 0.0)),
            "world_up_vector": list(payload.get("world_up_vector") or payload.get("worldUpVector") or (0.0, 1.0, 0.0)),
        }
        if settings["weights"] is None:
            settings.pop("weights")
        constraint = self.graph.add_constraint(kind, list(payload["drivers"]), driven, settings=settings)
        if maintain_offset:
            try:
                constrained_world_matrix = evaluate_rig_graph(self.graph).world_matrices.get(driven)
                if constrained_world_matrix is None:
                    raise ValueError(f"Constraint did not evaluate driven node: {driven}")
                settings["offset_matrix"] = calculate_constraint_offset_matrix(
                    current_world_matrix,
                    constrained_world_matrix,
                )
                self.graph.constraints[constraint]["settings"] = settings
            except Exception:
                self.graph.constraints.pop(constraint, None)
                raise
        return self._ok("rig.create_constraint", f"Created {kind} constraint.", created_ids=[constraint])

    def _op_rig_create_ik_fk_limb(self, payload: dict[str, Any]) -> RiggingOperationResult:
        start, mid, end = (str(payload[key]) for key in ("start", "mid", "end"))
        module = str(payload.get("module") or end + "_limb")
        parent = str(payload.get("parent") or "")
        created: list[str] = []
        fk_controls = []
        for joint_id in (start, mid, end):
            control_id = f"{module}_{self.graph.joints[joint_id]['name']}_fk_ctrl"
            self.graph.add_node(
                control_id, "dag.control", parent_id=parent, node_id=control_id,
                attributes={"matrix": self._joint_world_matrix(joint_id), "control_shape": "circle", "rig_module": module},
            )
            fk_controls.append(control_id)
            created.append(control_id)
            parent = control_id
        ik_target = str(payload.get("target") or f"{module}_ik_ctrl")
        if ik_target not in self.graph.nodes:
            self.graph.add_node(
                ik_target, "dag.control", node_id=ik_target,
                attributes={"matrix": self._joint_world_matrix(end), "control_shape": "cube", "rig_module": module},
            )
            created.append(ik_target)
        pole = str(payload.get("pole") or f"{module}_pole_ctrl")
        if pole not in self.graph.nodes:
            pole_matrix = self._pole_matrix(start, mid, end)
            self.graph.add_node(
                pole, "dag.control", node_id=pole,
                attributes={"matrix": pole_matrix, "control_shape": "diamond", "rig_module": module},
            )
            created.append(pole)
        solver = self.graph.add_ik_solver(start, mid, end, ik_target, pole_node_id=pole, solver_id=f"{module}_ik_solver",
                                          settings={"rig_module": module, "ik_fk_blend": float(payload.get("blend", 1.0))})
        created.append(solver)
        for control, joint in zip(fk_controls, (start, mid, end)):
            created.append(self.graph.add_constraint("orient", [control], joint,
                                                     settings={"rig_module": module, "ik_fk_role": "fk"}))
        return self._ok("rig.create_ik_fk_limb", f"Created IK/FK limb {module}.", created_ids=created,
                        data={"module": module, "fk_controls": fk_controls, "ik_control": ik_target, "pole_control": pole})

    def _op_rig_set_ik_fk_blend(self, payload: dict[str, Any]) -> RiggingOperationResult:
        module, blend = str(payload["limb"]), max(0.0, min(1.0, float(payload["blend"])))
        changed = []
        for item_id, item in self.graph.constraints.items():
            settings = item.setdefault("settings", {})
            if str(settings.get("rig_module") or "") != module:
                continue
            settings["ik_fk_blend"] = blend
            if item.get("type") == "ik":
                item["enabled"] = blend > 0.0
            elif settings.get("ik_fk_role") == "fk":
                item["enabled"] = blend < 1.0
            changed.append(item_id)
        return self._ok("rig.set_ik_fk_blend", f"Set {module} IK/FK to {blend:.3f}.", changed_ids=changed)

    def _op_rig_create_space_switch(self, payload: dict[str, Any]) -> RiggingOperationResult:
        targets = [str(value) for value in payload["targets"]]
        names = list(payload.get("names") or targets)
        active = int(payload.get("active", 0) or 0)
        weights = [1.0 if index == active else 0.0 for index in range(len(targets))]
        switch_id = self.graph.add_constraint(
            str(payload.get("mode") or "parent"), targets, str(payload["driven"]),
            settings={"weights": weights, "space_names": names, "active_space": active,
                      "rig_module": str(payload.get("module") or "space_switch")},
        )
        return self._ok("rig.create_space_switch", "Created space switch.", created_ids=[switch_id], data={"space_switch": switch_id})

    def _op_rig_set_space(self, payload: dict[str, Any]) -> RiggingOperationResult:
        switch_id = str(payload["space_switch"])
        constraint = self.graph.constraints.get(switch_id)
        if constraint is None:
            raise KeyError(f"Unknown space switch: {switch_id}")
        settings = constraint.setdefault("settings", {})
        names = list(settings.get("space_names") or constraint.get("source_ids") or [])
        requested = payload["space"]
        active = names.index(requested) if isinstance(requested, str) and requested in names else int(requested)
        if active < 0 or active >= len(names):
            raise IndexError("Space index is outside the switch target range.")
        settings["active_space"] = active
        settings["weights"] = [1.0 if index == active else 0.0 for index in range(len(names))]
        return self._ok("rig.set_space", f"Activated space {names[active]}.", changed_ids=[switch_id])

    def _op_rig_create_motion_path(self, payload: dict[str, Any]) -> RiggingOperationResult:
        curve = payload["curve"]
        if isinstance(curve, str):
            curve_node = self.graph.nodes.get(curve, {})
            curve = (curve_node.get("attributes") or {}).get("control_points") or []
        solver = self.graph.add_motion_path(
            str(payload["target"]), curve, parameter=float(payload.get("parameter", 0.0)),
            follow=bool(payload.get("follow", True)), closed=bool(payload.get("closed", False)),
        )
        return self._ok("rig.create_motion_path", "Created motion path rig.", created_ids=[solver])

    def _op_rig_create_ribbon(self, payload: dict[str, Any]) -> RiggingOperationResult:
        chain = [str(value) for value in payload["joint_chain"]]
        if len(chain) < 2:
            raise ValueError("A ribbon rig requires at least two joints.")
        positions = [self._joint_world_matrix(joint)[12:15] for joint in chain]
        width = float(payload.get("width", 1.0) or 1.0)
        if width <= 0.0:
            raise ValueError("Ribbon width must be positive.")
        up_vector = tuple(float(value) for value in (payload.get("up_vector") or (0.0, 1.0, 0.0))[:3])
        grid = _stable_ribbon_grid(positions, width=width, up_vector=up_vector)
        created = []
        denominator = max(1, len(chain) - 1)
        for index, joint in enumerate(chain):
            created.append(self.graph.add_ribbon_attachment(
                joint,
                grid,
                u=0.5,
                v=index / denominator,
                frame_method="parallel_transport",
                up_vector=up_vector,
            ))
        return self._ok(
            "rig.create_ribbon",
            "Created stable parallel-transport ribbon attachments.",
            created_ids=created,
            data={"frame_method": "parallel_transport", "width": width},
        )

    def _op_rig_create_twist(self, payload: dict[str, Any]) -> RiggingOperationResult:
        start, end = str(payload["start"]), str(payload["end"])
        twists = [str(value) for value in payload.get("twist_joints") or []]
        created = []
        for index, joint in enumerate(twists, 1):
            weight = index / (len(twists) + 1.0)
            created.append(self.graph.add_constraint("orient", [start, end], joint,
                                                     settings={"weights": [1.0 - weight, weight], "twist": True}))
        return self._ok("rig.create_twist", "Created twist distribution.", created_ids=created)

    def _op_rig_create_reverse_foot(self, payload: dict[str, Any]) -> RiggingOperationResult:
        ankle, ball, toe = (str(payload[key]) for key in ("ankle", "ball", "toe"))
        module = str(payload.get("module") or ankle + "_reverse_foot")
        created = []
        parent = ""
        for role, target in (("heel", ankle), ("toe", toe), ("ball", ball), ("ankle", ankle)):
            node_id = f"{module}_{role}_pivot"
            self.graph.add_node(node_id, "dag.control", parent_id=parent, node_id=node_id,
                                attributes={"matrix": self._joint_world_matrix(target), "control_shape": "pivot",
                                            "rig_module": module, "reverse_foot_role": role})
            created.append(node_id)
            parent = node_id
        created.append(self.graph.add_constraint("parent", [parent], ankle, settings={"rig_module": module}))
        return self._ok("rig.create_reverse_foot", "Created reverse-foot pivot hierarchy.", created_ids=created)

    def _op_rig_create_mesh_attachment(self, payload: dict[str, Any]) -> RiggingOperationResult:
        constraint = self.graph.add_constraint(
            "geometry", [str(payload["mesh"])], str(payload["driven"]),
            settings={"uv": list(payload.get("uv") or (0.5, 0.5)), "normal": list(payload.get("normal") or (0, 1, 0))},
        )
        return self._ok("rig.create_mesh_attachment", "Created portable mesh attachment.", created_ids=[constraint],
                        warnings=["Viewport evaluation requires resolved mesh surface sampling; engine export bakes the attachment."])

    def _op_rig_create_pose_reader(self, payload: dict[str, Any]) -> RiggingOperationResult:
        node_id = str(payload.get("name") or f"{payload['driver']}_pose_reader")
        self.graph.add_node(node_id, "utility.pose_reader", node_id=node_id,
                            attributes={"driver": str(payload["driver"]), "axis": str(payload.get("axis") or "x"),
                                        "range": list(payload.get("range") or (-90.0, 90.0)), "output": 0.0})
        return self._ok("rig.create_pose_reader", "Created pose reader.", created_ids=[node_id],
                        data={"driver": str(payload["driver"]), "axis": str(payload.get("axis") or "x")})

    def _op_rig_build_full(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload["definition"])
        validation = validate_character_definition(definition, self.scene_joints())
        if not validation.ok:
            raise ValueError("Cannot build an invalid character definition: " + ", ".join(validation.missing_required))
        modules = list(payload.get("modules") or (
            "root", "pelvis", "spine", "neck", "head", "left_arm", "right_arm", "left_leg", "right_leg", "fingers", "face"
        ))
        created = []
        for module in modules:
            result = self._build_module(str(module), definition, dict(payload.get("options") or {}))
            if not result.ok:
                raise RuntimeError(result.message)
            created.extend(result.created_ids)
        return self._ok("rig.build_full", f"Built {len(modules)} rig modules.", created_ids=created,
                        data={"modules": modules, "definition": definition.name})

    def _op_rig_build_module(self, payload: dict[str, Any]) -> RiggingOperationResult:
        return self._build_module(str(payload["module"]), self._definition(payload["definition"]),
                                  dict(payload.get("options") or {}))

    def _op_rig_remove_module(self, payload: dict[str, Any]) -> RiggingOperationResult:
        module = str(payload["module"])
        removed = self._remove_module(module)
        return self._ok("rig.remove_module", f"Removed rig module {module}.", removed_ids=removed)

    def _op_rig_rebuild_module(self, payload: dict[str, Any]) -> RiggingOperationResult:
        module = str(payload["module"])
        removed = self._remove_module(module)
        result = self._build_module(module, self._definition(payload["definition"]), dict(payload.get("options") or {}))
        result.capability = "rig.rebuild_module"
        result.removed_ids = removed
        return result

    def _op_rig_create_face_module(self, payload: dict[str, Any]) -> RiggingOperationResult:
        module = str(payload["module"])
        return self._build_face_module(module, self._definition(payload["definition"]))

    def _op_rig_store_connections(self, payload: dict[str, Any]) -> RiggingOperationResult:
        module = str(payload["module"])
        data = {
            "nodes": [copy.deepcopy(row) for row in self.graph.nodes.values()
                      if str((row.get("attributes") or {}).get("rig_module") or "") == module],
            "constraints": [copy.deepcopy(row) for row in self.graph.constraints.values()
                            if str((row.get("settings") or {}).get("rig_module") or "") == module],
        }
        return self._ok("rig.store_connections", f"Stored {module} connections.", data=data)

    def _op_rig_restore_connections(self, payload: dict[str, Any]) -> RiggingOperationResult:
        module = str(payload["module"])
        restored = []
        for item in payload.get("constraints") or []:
            constraint_id = str(item.get("id") or "")
            if constraint_id:
                self.graph.constraints[constraint_id] = copy.deepcopy(item)
                restored.append(constraint_id)
        return self._ok("rig.restore_connections", f"Restored {module} connections.", changed_ids=restored)

    def _op_retarget_solve_pose(self, payload: dict[str, Any]) -> RiggingOperationResult:
        target = self._definition(payload["target"])
        source_pose = dict(payload["source"])
        root_motion = bool(payload.get("root_motion", True))
        scale = float(payload.get("scale", 1.0) or 1.0)
        changed = []
        for slot, target_joint in target.slots.items():
            matrix = source_pose.get(slot)
            if not isinstance(matrix, (list, tuple)) or len(matrix) != 16 or target_joint not in self.graph.joints:
                continue
            solved = [float(value) for value in matrix]
            if slot == "Hips" and root_motion:
                solved[12:15] = [value * scale for value in solved[12:15]]
            elif slot != "Hips":
                rest = target.reference_pose.get(target_joint)
                if rest:
                    solved[12:15] = list(rest[12:15])
            self.graph.joints[target_joint]["local_matrix"] = solved
            if target_joint in self.graph.nodes:
                self.graph.nodes[target_joint].setdefault("attributes", {})["matrix"] = solved
            changed.append(target_joint)
        return self._ok("retarget.solve_pose", f"Solved {len(changed)} mapped joints.", changed_ids=changed)

    def _op_retarget_preview(self, payload: dict[str, Any]) -> RiggingOperationResult:
        result = self._op_retarget_solve_pose(payload)
        result.capability = "retarget.preview"
        result.message = "Previewed retarget pose in the TC rig graph."
        return result

    def _op_retarget_bake(self, payload: dict[str, Any]) -> RiggingOperationResult:
        frames = list(payload["source"])
        target = self._definition(payload["target"])
        start, end = payload["range"]
        sample_rate = max(1, int(payload.get("sample_rate", 1) or 1))
        clip_id = str(payload.get("clip_id") or f"{target.name}_retarget")
        samples = []
        for frame, pose in enumerate(frames, int(start)):
            if frame > int(end) or (frame - int(start)) % sample_rate:
                continue
            samples.append({"frame": frame, "pose": copy.deepcopy(pose)})
        self.graph.animation[clip_id] = {
            "id": clip_id, "type": "retarget_clip", "target_definition": target.name,
            "start": int(start), "end": int(end), "sample_rate": sample_rate, "samples": samples,
        }
        return self._ok("retarget.bake", f"Baked {len(samples)} retarget samples.", created_ids=[clip_id])

    def _op_retarget_transfer_take(self, payload: dict[str, Any]) -> RiggingOperationResult:
        take = copy.deepcopy(payload["take"])
        target = self._definition(payload["target"])
        take_id = str(take.get("id") or take.get("name") or f"{target.name}_take")
        take.update({"id": take_id, "target_definition": target.name, "timecode": payload.get("timecode")})
        self.graph.animation[take_id] = take
        return self._ok("retarget.transfer_take", f"Transferred take {take_id}.", created_ids=[take_id])

    def _build_module(self, module: str, definition: CharacterDefinition, options: dict[str, Any]) -> RiggingOperationResult:
        module_key = module.strip().lower()
        limb_slots = {
            "left_arm": ("LeftArm", "LeftForeArm", "LeftHand"),
            "right_arm": ("RightArm", "RightForeArm", "RightHand"),
            "left_leg": ("LeftUpLeg", "LeftLeg", "LeftFoot"),
            "right_leg": ("RightUpLeg", "RightLeg", "RightFoot"),
        }
        if module_key in limb_slots:
            start, mid, end = (definition.slots[slot] for slot in limb_slots[module_key])
            return self._op_rig_create_ik_fk_limb({"start": start, "mid": mid, "end": end, "module": module_key, **options})
        if module_key in {"face", "brows", "eyes", "eyelids", "mouth", "tongue", "teeth"}:
            return self._build_face_module(module_key, definition)
        slots = {
            "root": ("Reference",), "pelvis": ("Hips",),
            "spine": ("Spine", "Spine1", "Spine2", "Spine3"),
            "neck": ("Neck", "Neck1"), "head": ("Head",),
            "fingers": FINGER_SLOTS,
        }.get(module_key)
        if slots is None:
            raise ValueError(f"Unknown rig module: {module}")
        created = []
        parent = ""
        for slot in slots:
            joint = definition.slots.get(slot)
            if not joint:
                continue
            control = f"{module_key}_{slot}_ctrl"
            if control in self.graph.nodes:
                continue
            result = self._op_rig_create_control({"target": joint, "control_id": control, "name": control,
                                                  "parent": parent, "shape": "circle", "module": module_key})
            created.extend(result.created_ids)
            parent = control
        return self._ok("rig.build_module", f"Built {module_key} module.", created_ids=created, data={"module": module_key})

    def _build_face_module(self, module: str, definition: CharacterDefinition) -> RiggingOperationResult:
        tokens = {
            "brows": ("Brow",), "eyes": ("Eye",), "eyelids": ("Lid",),
            "mouth": ("Lip", "Jaw"), "tongue": ("Tongue",), "teeth": ("Teeth",),
            "face": ("Brow", "Eye", "Lid", "Lip", "Jaw", "Tongue", "Teeth", "Nose"),
        }[module]
        created = []
        for slot, joint in definition.slots.items():
            if not any(token in slot for token in tokens):
                continue
            control = f"{module}_{slot}_ctrl"
            if control in self.graph.nodes:
                continue
            result = self._op_rig_create_control({"target": joint, "control_id": control, "name": control,
                                                  "shape": "circle", "size": 0.25, "module": module})
            created.extend(result.created_ids)
        return self._ok("rig.create_face_module", f"Built {module} facial module.", created_ids=created, data={"module": module})

    def _remove_module(self, module: str) -> list[str]:
        node_ids = {
            node_id for node_id, node in self.graph.nodes.items()
            if str((node.get("attributes") or {}).get("rig_module") or "") == module
        }
        constraint_ids = {
            item_id for item_id, item in self.graph.constraints.items()
            if str((item.get("settings") or {}).get("rig_module") or "") == module
            or item_id in node_ids
            or str(item.get("target_id") or "") in node_ids
            or bool(set(item.get("source_ids") or []) & node_ids)
        }
        connection_ids = {
            item_id for item_id, item in self.graph.connections.items()
            if str(item.get("source_node") or "") in node_ids or str(item.get("target_node") or "") in node_ids
        }
        for item_id in constraint_ids:
            self.graph.constraints.pop(item_id, None)
        for item_id in connection_ids:
            self.graph.connections.pop(item_id, None)
        for node_id in node_ids:
            if node_id not in self.graph.joints:
                self.graph.nodes.pop(node_id, None)
        return sorted(node_ids | constraint_ids | connection_ids)

    def _joint_depth(self, joint_id: str) -> int:
        depth, cursor, visited = 0, str(joint_id), set()
        while cursor and cursor not in visited:
            visited.add(cursor)
            cursor = str(self.graph.joints.get(cursor, {}).get("parent_id") or "")
            if cursor:
                depth += 1
        return depth

    def _joint_world_matrix(self, joint_id: str) -> list[float]:
        try:
            result = self.graph.evaluate_local()
            matrix = result.world_matrices.get(joint_id)
            if matrix:
                return list(matrix)
        except Exception:
            pass
        return list(self.graph.joints.get(joint_id, {}).get("local_matrix") or IDENTITY_MATRIX)

    def _node_world_matrix(self, node_id: str) -> list[float]:
        try:
            result = self.graph.evaluate_local()
            matrix = result.world_matrices.get(node_id)
            if matrix:
                return list(matrix)
        except Exception:
            pass
        return list((self.graph.nodes.get(node_id, {}).get("attributes") or {}).get("matrix") or IDENTITY_MATRIX)

    def _pole_matrix(self, start: str, mid: str, end: str) -> list[float]:
        a = self._joint_world_matrix(start)[12:15]
        b = self._joint_world_matrix(mid)[12:15]
        c = self._joint_world_matrix(end)[12:15]
        ac = [c[index] - a[index] for index in range(3)]
        length_sq = sum(value * value for value in ac)
        factor = sum((b[index] - a[index]) * ac[index] for index in range(3)) / max(length_sq, 1.0e-12)
        projection = [a[index] + factor * ac[index] for index in range(3)]
        offset = [b[index] - projection[index] for index in range(3)]
        magnitude = math.sqrt(sum(value * value for value in offset))
        if magnitude <= 1.0e-8:
            offset = [0.0, 0.0, 1.0]
            magnitude = 1.0
        chain_length = math.sqrt(length_sq)
        position = [b[index] + offset[index] / magnitude * max(chain_length * 0.5, 1.0) for index in range(3)]
        matrix = list(IDENTITY_MATRIX)
        matrix[12:15] = position
        return matrix


__all__ = ["TC_NATIVE_CAPABILITY_STATUS", "TCRiggingHostAdapter"]

