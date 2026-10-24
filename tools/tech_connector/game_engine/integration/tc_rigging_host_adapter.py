"""Tech Connector-native implementation of the shared rigging workspace API."""

from __future__ import annotations

import copy
import math
import re
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
    thumb_rig_contract,
    twist_driver_contract,
    validate_character_definition,
)


RIG_BEHAVIOR_REVISION = 7


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


def _sample_polyline_by_length(points: list[list[float]], count: int, *, closed: bool = False) -> tuple[list[list[float]], list[float]]:
    """Sample a portable curve polyline at equal arc-length intervals."""
    values = [[float(component) for component in point[:3]] for point in points]
    if len(values) < 2:
        raise ValueError("A curve requires at least two control points.")
    if closed and values[-1] != values[0]:
        values.append(list(values[0]))
    cumulative = [0.0]
    for first, second in zip(values[:-1], values[1:]):
        cumulative.append(cumulative[-1] + math.sqrt(sum(
            (second[axis] - first[axis]) ** 2 for axis in range(3)
        )))
    total = cumulative[-1]
    if total <= 1.0e-8:
        raise ValueError("Curve points are coincident.")
    denominator = count if closed else max(1, count - 1)
    parameters = [index / float(denominator) for index in range(count)]
    samples = []
    for parameter in parameters:
        distance = parameter * total
        segment = next(
            (index for index in range(len(cumulative) - 1) if cumulative[index + 1] >= distance),
            len(cumulative) - 2,
        )
        span = max(cumulative[segment + 1] - cumulative[segment], 1.0e-8)
        blend = (distance - cumulative[segment]) / span
        samples.append([
            values[segment][axis] + (values[segment + 1][axis] - values[segment][axis]) * blend
            for axis in range(3)
        ])
    return samples, parameters


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
            ik_matrix = list(IDENTITY_MATRIX)
            ik_matrix[12:15] = self._joint_world_matrix(end)[12:15]
            self.graph.add_node(
                ik_target, "dag.control", node_id=ik_target,
                attributes={"matrix": ik_matrix, "control_shape": "cube", "rig_module": module,
                            "world_oriented": True},
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
        switch = str(payload.get("switch") or f"{module}_switch_ctrl")
        if switch not in self.graph.nodes:
            self.graph.add_node(
                switch, "dag.control", node_id=switch,
                attributes={
                    "matrix": self._joint_world_matrix(end),
                    "control_shape": "diamond",
                    "rig_module": module,
                    "ikFkBlend": float(payload.get("blend", 1.0)),
                    "stretch": 0.0,
                    "stretch_min": 0.0,
                    "stretch_max": 1.0,
                },
            )
            self.graph.nodes[switch].setdefault("attribute_specs", {})["stretch"] = {
                "type": "float", "min": 0.0, "max": 1.0, "default": 0.0, "keyable": True,
            }
            created.append(switch)
        start_position = self._joint_world_matrix(start)[12:15]
        mid_position = self._joint_world_matrix(mid)[12:15]
        end_position = self._joint_world_matrix(end)[12:15]
        upper_length = math.sqrt(sum((mid_position[index] - start_position[index]) ** 2 for index in range(3)))
        lower_length = math.sqrt(sum((end_position[index] - mid_position[index]) ** 2 for index in range(3)))
        solver = self.graph.add_ik_solver(start, mid, end, ik_target, pole_node_id=pole, solver_id=f"{module}_ik_solver",
                                          settings={
                                              "rig_module": module,
                                              "ik_fk_blend": float(payload.get("blend", 1.0)),
                                              "stretch_control_id": switch,
                                              "stretch_attribute": "stretch",
                                              "rest_upper_length": upper_length,
                                              "rest_lower_length": lower_length,
                                              "measurement": "per_segment_distance",
                                              "distance_segments": [
                                                  {"start": start, "end": mid, "rest_length": upper_length},
                                                  {"start": mid, "end": end, "rest_length": lower_length},
                                              ],
                                          })
        created.append(solver)
        for control, joint in zip(fk_controls, (start, mid, end)):
            fk_constraint = self.graph.add_constraint(
                "orient", [control], joint,
                settings={"rig_module": module, "ik_fk_role": "fk"},
            )
            self.graph.constraints[fk_constraint]["enabled"] = float(payload.get("blend", 1.0)) < 1.0
            created.append(fk_constraint)
        return self._ok("rig.create_ik_fk_limb", f"Created IK/FK limb {module}.", created_ids=created,
                        data={"module": module, "fk_controls": fk_controls, "ik_control": ik_target,
                              "pole_control": pole, "switch_control": switch, "stretch_attribute": "stretch",
                              "controls_world_oriented": True, "bind_pose_preserved": True,
                              "behavior_revision": RIG_BEHAVIOR_REVISION})

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

    def _op_rig_create_curve_joints(self, payload: dict[str, Any]) -> RiggingOperationResult:
        curve_value = payload["curve"]
        closed = bool(payload.get("closed", False))
        curve_name = "curve"
        if isinstance(curve_value, str):
            curve_name = curve_value
            curve_node = self.graph.nodes.get(curve_value, {})
            attributes = curve_node.get("attributes") or {}
            points = attributes.get("control_points") or []
            closed = bool(attributes.get("closed", closed))
        else:
            points = curve_value
        count = int(payload.get("joint_count", 5) or 5)
        if count < 1:
            raise ValueError("Joint count must be at least 1.")
        samples, parameters = _sample_polyline_by_length(points, count, closed=closed)
        prefix = str(payload.get("name_prefix") or curve_name).split(":")[-1].removesuffix("_crv")
        keep_attached = bool(payload.get("keep_attached", True))
        joints = []
        solvers = []
        for index, (position, parameter) in enumerate(zip(samples, parameters), start=1):
            base_id = f"{prefix}_path_{index:02d}_jnt"
            joint_id = base_id
            suffix = 1
            while joint_id in self.graph.nodes or joint_id in self.graph.joints:
                suffix += 1
                joint_id = f"{base_id}_{suffix}"
            matrix = list(IDENTITY_MATRIX)
            matrix[12:15] = position
            self.graph.add_joint(joint_id, joint_id=joint_id, local_matrix=matrix)
            joints.append(joint_id)
            if keep_attached:
                solvers.append(self.graph.add_motion_path(
                    joint_id,
                    points,
                    parameter=parameter,
                    follow=True,
                    closed=closed,
                    solver_id=f"{joint_id}_motion_path",
                ))
        return self._ok(
            "rig.create_curve_joints",
            f"Created {len(joints)} joints along the curve.",
            created_ids=joints + solvers,
            data={"joints": joints, "motion_paths": solvers, "parameters": parameters,
                  "keep_attached": keep_attached, "closed": closed},
        )

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
            data={
                "frame_method": "parallel_transport",
                "width": width,
                "region": str(payload.get("region") or "surface"),
                "side": str(payload.get("side") or "c"),
            },
        )

    def _op_rig_create_twist(self, payload: dict[str, Any]) -> RiggingOperationResult:
        start, end = str(payload["start"]), str(payload["end"])
        twists = [str(value) for value in payload.get("twist_joints") or []]
        module = str(payload.get("module") or f"{start}_twist")
        start_parent = ""
        if start in self.graph.nodes:
            start_parent = str(self.graph.nodes[start].get("dag_parent_id") or "")
        settings = twist_driver_contract(
            start,
            parent=str(payload.get("parent") or start_parent or start),
            module=module,
            overrides=payload,
        )
        driver_id = (
            start[:-7] + "_twist_driver" if start.endswith("_driver")
            else start + "_twist_driver"
        )
        end_matrix = (
            self._node_world_matrix(end) if end in self.graph.nodes
            else self._joint_world_matrix(end)
        )
        driver_parent = start if start in self.graph.nodes else ""
        driver_attributes = {
                "matrix": end_matrix,
                "control_shape": "twist",
                "rig_module": module,
                "twist_driver": True,
                "driver_parent": start,
                "twist_contract_revision": settings["revision"],
                "world_up_object": settings["world_up_object"],
                "aim_target": settings["aim_target"],
                "world_up_type": settings["world_up_type"],
                "world_up_vector": settings["world_up_vector"],
                "up_vector": settings["up_vector"],
                "aim_offset": settings["aim_offset"],
                "maintain_offset": settings["maintain_offset"],
                "constraint_weight": settings["weight"],
        }
        if driver_id in self.graph.nodes:
            driver_node = self.graph.nodes[driver_id]
            if str(driver_node.get("dag_parent_id") or "") != driver_parent:
                driver_node["dag_parent_id"] = driver_parent
            driver_node.setdefault("attributes", {}).update(driver_attributes)
        else:
            self.graph.add_node(
                driver_id, "dag.control", parent_id=driver_parent,
                node_id=driver_id, attributes=driver_attributes,
            )
        created = [driver_id]
        for index, joint in enumerate(twists, 1):
            weight = index / (len(twists) + 1.0)
            created.append(self.graph.add_constraint("orient", [start, end], joint,
                                                     settings={"weights": [1.0 - weight, weight], "twist": True,
                                                               "rig_module": module}))
        return self._ok(
            "rig.create_twist", "Created twist distribution.", created_ids=created,
            data={
                "twist_driver": driver_id,
                "parent": start,
                "world_up_object": settings["world_up_object"],
                "constraint_settings": settings,
            },
        )

    def _op_skin_surface_spatial_smooth_brush(self, payload: dict[str, Any]) -> RiggingOperationResult:
        settings = {
            "radius": float(payload.get("radius", 1.0)),
            "strength": float(payload.get("strength", 0.5)),
            "iterations": int(payload.get("iterations", 1)),
            "max_influences": int(payload.get("max_influences", 8)),
            "normal_angle": float(payload.get("normal_angle", 120.0)),
            "max_neighbors": int(payload.get("max_neighbors", 96)),
        }
        self.graph.metadata["active_skin_brush"] = {
            "type": "surface_spatial_smooth",
            **settings,
        }
        return self._ok(
            "skin.surface_spatial_smooth_brush",
            "Activated the TC surface-spatial skin smoothing paint target.",
            data=settings,
        )

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

    def _apply_joint_world_matrices(self, targets: dict[str, list[float]]) -> list[str]:
        """Write world matrices back as hierarchy-correct local matrices."""
        import numpy as np

        changed = []
        ordered = sorted(
            (joint for joint in targets if joint in self.graph.joints),
            key=self._joint_depth,
        )
        for joint_id in ordered:
            world = np.asarray(targets[joint_id], dtype=float).reshape((4, 4))
            parent_id = str(self.graph.joints[joint_id].get("parent_id") or "")
            if parent_id:
                parent_world = np.asarray(
                    targets.get(parent_id) or self._joint_world_matrix(parent_id),
                    dtype=float,
                ).reshape((4, 4))
                local = world @ np.linalg.inv(parent_world)
            else:
                local = world
            values = local.reshape(-1).tolist()
            self.graph.joints[joint_id]["local_matrix"] = values
            if joint_id in self.graph.nodes:
                self.graph.nodes[joint_id].setdefault("attributes", {})["matrix"] = values
            changed.append(joint_id)
        return changed

    def _apply_face_joint_placement_rules(self, mesh_id: str = "") -> dict[str, Any]:
        """Apply portable brow, eyelid-tip, and centered-nose channel rules."""
        import numpy as np

        def short_name(joint_id: str) -> str:
            joint = self.graph.joints[joint_id]
            return str(joint.get("name") or joint_id).replace("\\", "|").rsplit("|", 1)[-1].rsplit(":", 1)[-1]

        mesh = self.graph.nodes.get(mesh_id, {})
        attributes = dict(mesh.get("attributes") or {})
        bounds = attributes.get("bounds") or attributes.get("bbox") or {}
        if isinstance(bounds, dict) and bounds.get("min") is not None and bounds.get("max") is not None:
            mesh_center = (
                np.asarray(bounds["min"], dtype=float) + np.asarray(bounds["max"], dtype=float)
            ) * 0.5
        else:
            mesh_center = np.zeros(3, dtype=float)
        targets: dict[str, list[float]] = {}
        brow_report = {}
        for side in ("l", "r"):
            rows = []
            for joint_id in self.graph.joints:
                match = re.match(rf"^{side}_brow(\d+|_end)$", short_name(joint_id), re.IGNORECASE)
                if match:
                    token = match.group(1).lower()
                    rows.append((6 if token == "_end" else int(token), joint_id))
            rows.sort()
            if len(rows) < 2:
                continue
            ids = [joint_id for _index, joint_id in rows]
            matrices = [np.asarray(self._joint_world_matrix(joint_id), dtype=float).reshape((4, 4)) for joint_id in ids]
            points = [matrix[3, :3].copy() for matrix in matrices]
            previous_y = None
            for index, (joint_id, matrix, origin) in enumerate(zip(ids, matrices, points)):
                x_axis = (points[index + 1] - origin) if index < len(points) - 1 else (origin - points[index - 1])
                x_axis /= max(float(np.linalg.norm(x_axis)), 1.0e-12)
                surface_normal = origin - mesh_center
                surface_normal -= x_axis * float(np.dot(surface_normal, x_axis))
                if float(np.linalg.norm(surface_normal)) <= 1.0e-8:
                    surface_normal = matrix[2, :3]
                    surface_normal -= x_axis * float(np.dot(surface_normal, x_axis))
                surface_normal /= max(float(np.linalg.norm(surface_normal)), 1.0e-12)
                y_axis = np.cross(surface_normal, x_axis)
                if float(np.dot(y_axis, np.asarray((0.0, 1.0, 0.0)))) < 0.0:
                    y_axis *= -1.0
                    surface_normal *= -1.0
                y_axis /= max(float(np.linalg.norm(y_axis)), 1.0e-12)
                z_axis = np.cross(x_axis, y_axis)
                z_axis /= max(float(np.linalg.norm(z_axis)), 1.0e-12)
                matrix[0, :3], matrix[1, :3], matrix[2, :3] = x_axis, y_axis, z_axis
                targets[joint_id] = matrix.reshape(-1).tolist()
                brow_report[short_name(joint_id)] = {
                    "x_next_brow_alignment": 1.0,
                    "y_surface_tangent_alignment": 1.0,
                    "adjacent_y_alignment": float(np.dot(previous_y, y_axis)) if previous_y is not None else 1.0,
                }
                previous_y = y_axis
        surface_report = {}

        def orient_surface_joint(joint_id: str, _tangent_reference: Any) -> None:
            matrix = np.asarray(
                targets.get(joint_id) or self._joint_world_matrix(joint_id),
                dtype=float,
            ).reshape((4, 4))
            origin = matrix[3, :3].copy()
            normal = origin - mesh_center
            if float(np.linalg.norm(normal)) <= 1.0e-8:
                normal = matrix[2, :3].copy()
            normal /= max(float(np.linalg.norm(normal)), 1.0e-12)
            y_axis = np.asarray((0.0, 1.0, 0.0), dtype=float)
            y_axis -= normal * float(np.dot(y_axis, normal))
            if float(np.linalg.norm(y_axis)) <= 1.0e-8:
                current_y = matrix[1, :3].copy()
                y_axis = current_y - normal * float(np.dot(current_y, normal))
            if float(np.linalg.norm(y_axis)) <= 1.0e-8:
                return
            y_axis /= max(float(np.linalg.norm(y_axis)), 1.0e-12)
            x_axis = np.cross(y_axis, normal)
            x_axis /= max(float(np.linalg.norm(x_axis)), 1.0e-12)
            z_axis = np.cross(x_axis, y_axis)
            z_axis /= max(float(np.linalg.norm(z_axis)), 1.0e-12)
            matrix[0, :3], matrix[1, :3], matrix[2, :3] = x_axis, y_axis, z_axis
            targets[joint_id] = matrix.reshape(-1).tolist()
            surface_report[short_name(joint_id)] = {
                "x_surface_tangent_alignment": 1.0,
                "y_outward_view_up_alignment": float(
                    np.dot(y_axis, np.asarray((0.0, 1.0, 0.0)))
                ),
                "z_surface_normal_alignment": abs(float(np.dot(z_axis, normal))),
            }

        for side in ("l", "r"):
            under_rows = []
            for joint_id in self.graph.joints:
                match = re.match(
                    rf"^{side}_under_?eye_?(\d+)$",
                    short_name(joint_id),
                    re.IGNORECASE,
                )
                if match:
                    under_rows.append((int(match.group(1)), joint_id))
            under_rows.sort()
            under_ids = [joint_id for _index, joint_id in under_rows]
            under_points = {
                joint_id: np.asarray(
                    targets.get(joint_id) or self._joint_world_matrix(joint_id),
                    dtype=float,
                ).reshape((4, 4))[3, :3].copy()
                for joint_id in under_ids
            }
            for index, joint_id in enumerate(under_ids):
                neighbor = (
                    under_ids[index + 1]
                    if index < len(under_ids) - 1
                    else under_ids[index - 1] if index else ""
                )
                if neighbor:
                    direction = (
                        under_points[neighbor] - under_points[joint_id]
                        if index < len(under_ids) - 1
                        else under_points[joint_id] - under_points[neighbor]
                    )
                    orient_surface_joint(joint_id, direction)
            for joint_id in self.graph.joints:
                if re.match(
                    rf"^{side}_.+cheek.*$",
                    short_name(joint_id),
                    re.IGNORECASE,
                ):
                    current = np.asarray(
                        targets.get(joint_id) or self._joint_world_matrix(joint_id),
                        dtype=float,
                    ).reshape((4, 4))
                    orient_surface_joint(joint_id, current[0, :3])

        changed = self._apply_joint_world_matrices(targets) if targets else []

        eyelid_tips = []
        tip_pattern = re.compile(r"^(?:l|r)_(?:inner|outer|upper|lower)_eyelidTip\d*$", re.IGNORECASE)
        for joint_id, joint in self.graph.joints.items():
            if not tip_pattern.match(short_name(joint_id)):
                continue
            local = list(joint.get("local_matrix") or IDENTITY_MATRIX)
            local[:12] = list(IDENTITY_MATRIX[:12])
            joint["local_matrix"] = local
            self.graph.nodes[joint_id].setdefault("attributes", {})["matrix"] = list(local)
            self.graph.nodes[joint_id]["attributes"]["rotate"] = [0.0, 0.0, 0.0]
            eyelid_tips.append(joint_id)

        nose_base = next((joint_id for joint_id in self.graph.joints if short_name(joint_id).lower() == "nose_base"), "")
        if nose_base:
            local = list(self.graph.joints[nose_base].get("local_matrix") or IDENTITY_MATRIX)
            local[12] = 0.0
            self.graph.joints[nose_base]["local_matrix"] = local
            self.graph.nodes[nose_base].setdefault("attributes", {})["matrix"] = list(local)
            changed.append(nose_base)
        return {"brows": brow_report, "surface_face": surface_report,
                "eyelid_tip_zero_rotates": eyelid_tips, "nose_base_translate_x": 0.0 if nose_base else None,
                "changed_ids": list(dict.fromkeys(changed + eyelid_tips))}

    def _delete_auto_joint_guides(self) -> list[str]:
        """Remove TC-native temporary guide nodes and their graph edges."""
        roots = {
            node_id for node_id, node in self.graph.nodes.items()
            if node_id == "auto_joint_guides_grp"
            or str(node.get("name") or "").rsplit(":", 1)[-1]
            == "auto_joint_guides_grp"
        }
        removed = set(roots)
        while True:
            children = {
                node_id for node_id, node in self.graph.nodes.items()
                if str(node.get("dag_parent_id") or "") in removed
            }
            new_children = children - removed
            if not new_children:
                break
            removed.update(new_children)
        removed.difference_update(self.graph.joints)
        if not removed:
            return []
        for item_id, item in list(self.graph.constraints.items()):
            referenced = {
                str(item.get("target_id") or ""),
                *(str(value) for value in (item.get("source_ids") or [])),
            }
            if referenced & removed:
                self.graph.constraints.pop(item_id, None)
        for item_id, item in list(self.graph.connections.items()):
            if {
                str(item.get("source_node") or ""),
                str(item.get("target_node") or ""),
            } & removed:
                self.graph.connections.pop(item_id, None)
        for node_id in removed:
            self.graph.nodes.pop(node_id, None)
        return sorted(removed)

    def _op_rig_place_joints(self, payload: dict[str, Any]) -> RiggingOperationResult:
        """Place TC graph joints from explicit points or mesh bounds."""
        definition = self._definition(payload["definition"])
        positions = dict(payload.get("positions") or {})
        mesh_id = str(payload.get("mesh") or "")
        if not positions:
            if not mesh_id:
                mesh_id = next((node for node in self.selected_ids if node in self.graph.nodes), "")
            mesh = self.graph.nodes.get(mesh_id, {})
            attributes = dict(mesh.get("attributes") or {})
            bounds = attributes.get("bounds") or attributes.get("bbox") or {}
            minimum = bounds.get("min") if isinstance(bounds, dict) else None
            maximum = bounds.get("max") if isinstance(bounds, dict) else None
            vertices = attributes.get("vertices") or attributes.get("positions") or []
            if (minimum is None or maximum is None) and vertices:
                minimum = [min(float(point[axis]) for point in vertices) for axis in range(3)]
                maximum = [max(float(point[axis]) for point in vertices) for axis in range(3)]
            if minimum is None or maximum is None:
                raise ValueError(
                    "Tech Connector joint placement requires semantic positions or mesh bounds."
                )
            source = {
                slot: self._joint_world_matrix(joint_id)[12:15]
                for slot, joint_id in definition.slots.items()
                if joint_id in self.graph.joints
            }
            source_min = [min(point[axis] for point in source.values()) for axis in range(3)]
            source_max = [max(point[axis] for point in source.values()) for axis in range(3)]
            for slot, point in source.items():
                fitted = []
                for axis in range(3):
                    span = source_max[axis] - source_min[axis]
                    fraction = (point[axis] - source_min[axis]) / span if abs(span) > 1.0e-8 else 0.5
                    fitted.append(float(minimum[axis]) + fraction * (float(maximum[axis]) - float(minimum[axis])))
                positions[slot] = fitted
        if bool(payload.get("preview", False)):
            return self._ok(
                "rig.place_joints",
                "Previewed TC joint placement.",
                data={"positions": positions, "applied": False,
                      "behavior_revision": RIG_BEHAVIOR_REVISION},
            )
        targets = {}
        for key, position in positions.items():
            joint_id = definition.slots.get(str(key), str(key))
            if joint_id not in self.graph.joints:
                continue
            matrix = self._joint_world_matrix(joint_id)
            matrix[12:15] = [float(value) for value in position]
            targets[joint_id] = matrix
        changed = self._apply_joint_world_matrices(targets)
        face_rules = self._apply_face_joint_placement_rules(mesh_id)
        changed.extend(face_rules.pop("changed_ids"))
        removed_guides = self._delete_auto_joint_guides()
        return self._ok(
            "rig.place_joints",
            f"Placed {len(changed)} TC joints.",
            changed_ids=changed,
            data={"positions": positions, "applied": True, "face_orientation": face_rules,
                  "removed_auto_joint_guides": removed_guides,
                  "behavior_revision": RIG_BEHAVIOR_REVISION},
        )

    def _op_rig_set_t_pose(self, payload: dict[str, Any]) -> RiggingOperationResult:
        """Set a TC graph biped to a deterministic world-axis T-pose."""
        import numpy as np

        definition = self._definition(payload["definition"])
        supplied = dict(payload.get("pose_matrices") or {})
        if supplied:
            targets = {
                definition.slots.get(str(key), str(key)): [float(value) for value in values]
                for key, values in supplied.items()
            }
            changed = self._apply_joint_world_matrices(targets)
            return self._ok("rig.set_t_pose", "Applied portable TC T-pose matrices.", changed_ids=changed)

        targets = {}
        current = {
            joint_id: self._joint_world_matrix(joint_id)
            for joint_id in set(definition.slots.values()) if joint_id in self.graph.joints
        }

        def position(joint_id: str) -> np.ndarray:
            return np.asarray(current[joint_id][12:15], dtype=float)

        def basis(x_axis, up_axis, origin):
            x_axis = np.asarray(x_axis, dtype=float)
            x_axis /= max(np.linalg.norm(x_axis), 1.0e-8)
            up_axis = np.asarray(up_axis, dtype=float)
            up_axis -= x_axis * float(np.dot(up_axis, x_axis))
            up_axis /= max(np.linalg.norm(up_axis), 1.0e-8)
            z_axis = np.cross(x_axis, up_axis)
            matrix = np.identity(4, dtype=float)
            matrix[0, :3], matrix[1, :3], matrix[2, :3] = x_axis, up_axis, z_axis
            matrix[3, :3] = origin
            return matrix.reshape(-1).tolist()

        for slot in ("Reference", "Hips"):
            joint_id = definition.slots.get(slot, "")
            if joint_id in current:
                world = list(IDENTITY_MATRIX)
                world[12:15] = current[joint_id][12:15]
                targets[joint_id] = world

        for side, outward in (("Left", 1.0), ("Right", -1.0)):
            arm_slots = (side + "Arm", side + "ForeArm", side + "Hand")
            arm_ids = [definition.slots.get(slot, "") for slot in arm_slots]
            if all(joint in current for joint in arm_ids):
                first, middle, end = arm_ids
                upper_length = float(np.linalg.norm(position(middle) - position(first)))
                lower_length = float(np.linalg.norm(position(end) - position(middle)))
                first_position = position(first)
                middle_position = first_position + np.asarray((outward * upper_length, 0.0, 0.0))
                end_position = middle_position + np.asarray((outward * lower_length, 0.0, 0.0))
                child_tx = float(self.graph.joints[middle].get("local_matrix", IDENTITY_MATRIX)[12])
                aim_sign = 1.0 if child_tx >= 0.0 else -1.0
                x_axis = (outward * aim_sign, 0.0, 0.0)
                up_axis = (0.0, aim_sign, 0.0)
                targets[first] = basis(x_axis, up_axis, first_position)
                targets[middle] = basis(x_axis, up_axis, middle_position)
                hand_world = list(current[end])
                hand_world[12:15] = end_position.tolist()
                targets[end] = hand_world

            leg_slots = (side + "UpLeg", side + "Leg", side + "Foot")
            leg_ids = [definition.slots.get(slot, "") for slot in leg_slots]
            if all(joint in current for joint in leg_ids):
                first, middle, end = leg_ids
                upper_length = float(np.linalg.norm(position(middle) - position(first)))
                lower_length = float(np.linalg.norm(position(end) - position(middle)))
                first_position = position(first)
                middle_position = first_position + np.asarray((0.0, -upper_length, 0.0))
                end_position = middle_position + np.asarray((0.0, -lower_length, 0.0))
                child_tx = float(self.graph.joints[middle].get("local_matrix", IDENTITY_MATRIX)[12])
                aim_sign = 1.0 if child_tx >= 0.0 else -1.0
                x_axis = (0.0, -aim_sign, 0.0)
                up_axis = (aim_sign, 0.0, 0.0)
                targets[first] = basis(x_axis, up_axis, first_position)
                targets[middle] = basis(x_axis, up_axis, middle_position)
                foot_world = list(current[end])
                foot_world[12:15] = end_position.tolist()
                targets[end] = foot_world

            foot_id = definition.slots.get(side + "Foot", "")
            toe_id = definition.slots.get(side + "ToeBase", "")
            if foot_id in current and toe_id in current:
                foot_position = np.asarray((targets.get(foot_id) or current[foot_id])[12:15], dtype=float)
                toe_position = np.asarray(current[toe_id][12:15], dtype=float)
                direction = toe_position - foot_position
                direction[1] = 0.0
                if float(np.linalg.norm(direction)) > 1.0e-8:
                    targets[foot_id] = basis(direction, (0.0, 1.0, 0.0), foot_position)

        grounded_by = 0.0
        if bool(payload.get("ground", True)):
            contacts = []
            for side in ("Left", "Right"):
                for slot in (side + "Foot", side + "ToeBase"):
                    joint_id = definition.slots.get(slot, "")
                    if joint_id in current:
                        contacts.append(float((targets.get(joint_id) or current[joint_id])[13]))
            if contacts:
                grounded_by = -min(contacts)
                for joint_id in current:
                    world = list(targets.get(joint_id) or current[joint_id])
                    world[13] += grounded_by
                    targets[joint_id] = world

        changed = self._apply_joint_world_matrices(targets)
        return self._ok(
            "rig.set_t_pose",
            "Set TC character T-pose.",
            changed_ids=changed,
            data={"behavior_revision": RIG_BEHAVIOR_REVISION, "world_up_axis": "Y",
                  "grounded_by": grounded_by, "foot_alignment": "rotation_only"},
        )
    def _op_rig_build_full(self, payload: dict[str, Any]) -> RiggingOperationResult:
        definition = self._definition(payload["definition"])
        validation = validate_character_definition(definition, self.scene_joints())
        if not validation.ok:
            raise ValueError("Cannot build an invalid character definition: " + ", ".join(validation.missing_required))
        options = dict(payload.get("options") or {})
        t_pose_result = None
        if bool(options.get("set_t_pose", True)):
            t_pose_result = self._op_rig_set_t_pose({
                "definition": definition.to_dict(),
                "ground": bool(options.get("ground", True)),
                "pose_matrices": payload.get("pose_matrices") or {},
            })
        options.setdefault("blend", float(options.get("ik_fk_blend", 1.0)))
        modules = list(payload.get("modules") or (
            "root", "pelvis", "spine", "neck", "head", "left_arm", "right_arm", "left_leg", "right_leg", "fingers", "face"
        ))
        created = []
        for module in modules:
            result = self._build_module(str(module), definition, options)
            if not result.ok:
                raise RuntimeError(result.message)
            created.extend(result.created_ids)
        return self._ok("rig.build_full", f"Built {len(modules)} rig modules.", created_ids=created,
                        data={"modules": modules, "definition": definition.name,
                              "t_pose": t_pose_result.to_dict() if t_pose_result else None,
                              "behavior_revision": RIG_BEHAVIOR_REVISION})

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

    def _build_thumb_rigs(self, definition: CharacterDefinition, blend: float) -> list[str]:
        """Build the shared Maya-compatible four-joint thumb contract in TC."""
        import numpy as np

        created: list[str] = []
        blend = max(0.0, min(1.0, float(blend)))
        for contract in thumb_rig_contract(definition):
            joints = list(contract["joints"])
            if any(joint not in self.graph.joints for joint in joints):
                continue
            module = "fingers"
            bind_world = {joint: self._joint_world_matrix(joint) for joint in joints}
            joint_positions = [np.asarray(bind_world[joint][12:15], dtype=float) for joint in joints]

            parent_control = ""
            parent_world = np.identity(4, dtype=float)
            for joint, control_id in zip(contract["fk_joints"], contract["fk_controls"]):
                world = np.asarray(bind_world[joint], dtype=float).reshape((4, 4))
                local = world @ np.linalg.inv(parent_world) if parent_control else world
                if control_id not in self.graph.nodes:
                    self.graph.add_node(
                        control_id,
                        "dag.control",
                        parent_id=parent_control,
                        node_id=control_id,
                        attributes={
                            "matrix": local.reshape(-1).tolist(),
                            "control_shape": "cube",
                            "rig_module": module,
                            "thumb_role": "fk",
                            "channels_locked": False,
                            "thumb_contract_revision": contract["revision"],
                        },
                    )
                    created.append(control_id)
                constraint_id = self.graph.add_constraint(
                    "orient",
                    [control_id],
                    joint,
                    settings={"rig_module": module, "ik_fk_role": "fk", "thumb_contract": True},
                )
                self.graph.constraints[constraint_id]["enabled"] = blend < 1.0
                created.append(constraint_id)
                parent_control = control_id
                parent_world = world

            ik_control = str(contract["ik_control"])
            ik_matrix = list(IDENTITY_MATRIX)
            ik_matrix[12:15] = joint_positions[-1].tolist()
            if ik_control not in self.graph.nodes:
                self.graph.add_node(
                    ik_control,
                    "dag.control",
                    node_id=ik_control,
                    attributes={
                        "matrix": ik_matrix,
                        "control_shape": "cube",
                        "rig_module": module,
                        "thumb_role": "ik",
                        "world_oriented": True,
                        "channels_locked": False,
                        "thumb_contract_revision": contract["revision"],
                    },
                )
                created.append(ik_control)

            root, endpoint = joint_positions[0], joint_positions[-1]
            axis = endpoint - root
            axis_length_sq = float(np.dot(axis, axis))
            deviations = []
            for position in joint_positions[1:-1]:
                factor = float(np.dot(position - root, axis)) / max(axis_length_sq, 1.0e-12)
                projection = root + axis * factor
                deviations.append((float(np.linalg.norm(position - projection)), projection, position - projection))
            _size, pole_origin, pole_direction = max(deviations, key=lambda item: item[0])
            if float(np.linalg.norm(pole_direction)) <= 1.0e-8:
                pole_direction = np.asarray((0.0, 0.0, 1.0), dtype=float)
            hand_slot = "LeftHand" if contract["side"] == "left" else "RightHand"
            hand_joint = definition.slots.get(hand_slot, "")
            if hand_joint in self.graph.joints:
                dorsal_direction = -np.asarray(
                    self._joint_world_matrix(hand_joint)[8:11], dtype=float
                )
                if float(np.dot(dorsal_direction, (0.0, 1.0, 0.0))) < 0.0:
                    dorsal_direction *= -1.0
                if axis_length_sq > 1.0e-12:
                    dorsal_direction -= axis * (
                        float(np.dot(dorsal_direction, axis)) / axis_length_sq
                    )
                if (
                    float(np.linalg.norm(dorsal_direction)) > 1.0e-8
                    and float(np.dot(pole_direction, dorsal_direction)) < 0.0
                ):
                    pole_direction *= -1.0
            pole_position = pole_origin + pole_direction / max(float(np.linalg.norm(pole_direction)), 1.0e-12) * 5.0
            pole_control = str(contract["pole_control"])
            pole_matrix = list(IDENTITY_MATRIX)
            pole_matrix[12:15] = pole_position.tolist()
            if pole_control not in self.graph.nodes:
                self.graph.add_node(
                    pole_control,
                    "dag.control",
                    node_id=pole_control,
                    attributes={
                        "matrix": pole_matrix,
                        "control_shape": "diamond",
                        "rig_module": module,
                        "thumb_role": "pole_vector",
                        "pole_side": contract["pole_side"],
                        "world_oriented": True,
                        "channels_locked": False,
                        "space": 0,
                        "space_names": ["IK", "Hand", "Composite"],
                        "thumb_contract_revision": contract["revision"],
                    },
                )
                self.graph.nodes[pole_control].setdefault("attribute_specs", {})["space"] = {
                    "type": "enum", "enum_names": ["IK", "Hand", "Composite"], "default": 0, "keyable": True,
                }
                created.append(pole_control)

            solver = self.graph.add_ik_chain_solver(
                joints,
                ik_control,
                pole_node_id=pole_control,
                solver_id=f"{contract['side']}_thumb_ik_solver",
                settings={
                    "rig_module": module,
                    "ik_fk_blend": blend,
                    "solver": "rotate_plane",
                    "bind_pose_preserved": True,
                    "thumb_contract_revision": contract["revision"],
                },
            )
            self.graph.constraints[solver]["enabled"] = blend > 0.0
            created.append(solver)

            # Match Maya's IK/hand/composite PV spaces with matched child
            # targets so changing space never snaps the control.
            space_parents = [ik_control, hand_joint, ""]
            space_names = ["ik", "hand", "composite"]
            space_targets = []
            pv_world = np.asarray(pole_matrix, dtype=float).reshape((4, 4))
            for name, parent_id in zip(space_names, space_parents):
                if parent_id and parent_id not in self.graph.nodes:
                    continue
                target_id = f"{pole_control}_{name}_spaceTarget"
                parent_matrix = (
                    np.asarray(self._node_world_matrix(parent_id), dtype=float).reshape((4, 4))
                    if parent_id else np.identity(4, dtype=float)
                )
                local = pv_world @ np.linalg.inv(parent_matrix)
                self.graph.add_node(
                    target_id,
                    "dag.transform",
                    parent_id=parent_id,
                    node_id=target_id,
                    attributes={"matrix": local.reshape(-1).tolist(), "rig_module": module, "visibility": False},
                )
                space_targets.append(target_id)
                created.append(target_id)
            space_constraint = self.graph.add_constraint(
                "parent",
                space_targets,
                pole_control,
                constraint_id=f"{pole_control}_space_constraint",
                settings={
                    "weights": [1.0] + [0.0] * (len(space_targets) - 1),
                    "space_names": ["IK", "Hand", "Composite"][:len(space_targets)],
                    "active_space": 0,
                    "rig_module": module,
                    "thumb_contract": True,
                },
            )
            created.append(space_constraint)
            # The local evaluator is ordered: update the PV space before the
            # solver consumes the pole control in the same evaluation pass.
            solver_constraint = self.graph.constraints.pop(solver)
            self.graph.constraints[solver] = solver_constraint
        return created

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
            limb = self._op_rig_create_ik_fk_limb(
                {"start": start, "mid": mid, "end": end, "module": module_key, **options}
            )
            if not limb.ok:
                return limb
            created = list(limb.created_ids)
            twist_routes = {
                "left_arm": ((start, mid, "LeftArmRoll"), (mid, end, "LeftForeArmRoll")),
                "right_arm": ((start, mid, "RightArmRoll"), (mid, end, "RightForeArmRoll")),
                "left_leg": ((start, mid, "LeftUpLegRoll"), (mid, end, "LeftLegRoll")),
                "right_leg": ((start, mid, "RightUpLegRoll"), (mid, end, "RightLegRoll")),
            }
            for twist_start, twist_end, slot in twist_routes[module_key]:
                twist_joint = definition.slots.get(slot)
                if not twist_joint:
                    continue
                twist = self._op_rig_create_twist({
                    "start": twist_start, "end": twist_end,
                    "twist_joints": [twist_joint], "module": module_key,
                })
                if not twist.ok:
                    return twist
                created.extend(twist.created_ids)
            return self._ok(
                "rig.build_module", f"Built {module_key} module.", created_ids=created,
                data={"module": module_key},
            )
        if module_key in {"face", "brows", "eyes", "eyelids", "mouth", "tongue", "teeth", "nose"}:
            return self._build_face_module(module_key, definition)
        slots = {
            "root": ("Reference",), "pelvis": ("Hips",),
            "spine": ("Spine", "Spine1", "Spine2", "Spine3"),
            "neck": ("Neck", "Neck1"), "head": ("Head",),
            "fingers": FINGER_SLOTS,
        }.get(module_key)
        if slots is None:
            raise ValueError(f"Unknown rig module: {module}")
        created = self._build_thumb_rigs(definition, float(options.get("blend", 1.0))) if module_key == "fingers" else []
        module_joints = []
        module_controls = []
        parent = ""
        resolved_slots = [slot for slot in slots if definition.slots.get(slot)]
        for slot in resolved_slots:
            if module_key == "fingers" and "HandThumb" in slot:
                continue
            joint = definition.slots.get(slot)
            if not joint:
                continue
            control = f"{module_key}_{slot}_ctrl"
            module_joints.append(joint)
            module_controls.append(control)
            if control in self.graph.nodes:
                parent = control
                continue
            use_spine_sub = module_key == "spine" and slot != resolved_slots[-1]
            result = self._op_rig_create_control({
                "target": joint,
                "control_id": control,
                "name": control,
                "parent": parent,
                "shape": "circle",
                "module": module_key,
                "constrain": not use_spine_sub,
            })
            created.extend(result.created_ids)
            if use_spine_sub:
                sub_control = control.removesuffix("_ctrl") + "_sub_ctrl"
                sub_result = self._op_rig_create_control({
                    "target": joint,
                    "control_id": sub_control,
                    "name": sub_control,
                    "parent": control,
                    "shape": "bi_arrow",
                    "module": module_key,
                    "constrain": True,
                })
                self.graph.nodes[sub_control].setdefault("attributes", {}).update({
                    "shape_rotation_x": 90.0,
                    "shape_rotation_space": "local_cvs",
                })
                created.extend(sub_result.created_ids)
            parent = control
        if module_key == "spine" and len(module_joints) >= 3:
            contiguous = all(
                str(self.graph.joints.get(child, {}).get("parent_id") or "") == str(parent_joint)
                for parent_joint, child in zip(module_joints[:-1], module_joints[1:])
            )
            pelvis_controls = [
                node_id for node_id, node in self.graph.nodes.items()
                if str((node.get("attributes") or {}).get("rig_module") or "") == "pelvis"
                and str(node.get("node_type") or node.get("type") or "") == "dag.control"
            ]
            if contiguous and pelvis_controls:
                pelvis_control = pelvis_controls[0]
                pelvis_attrs = self.graph.nodes[pelvis_control].setdefault("attributes", {})
                pelvis_attrs.setdefault("stretch", 0.0)
                pelvis_attrs.update({"stretch_min": 0.0, "stretch_max": 1.0})
                self.graph.nodes[pelvis_control].setdefault("attribute_specs", {})["stretch"] = {
                    "type": "float", "min": 0.0, "max": 1.0, "default": 0.0, "keyable": True,
                }
                rest_length = 0.0
                rest_lengths = []
                for first, second in zip(module_joints[:-1], module_joints[1:]):
                    first_position = self._joint_world_matrix(first)[12:15]
                    second_position = self._joint_world_matrix(second)[12:15]
                    segment_length = math.sqrt(sum(
                        (second_position[index] - first_position[index]) ** 2 for index in range(3)
                    ))
                    rest_lengths.append(segment_length)
                    rest_length += segment_length
                stretch_solver = self.graph.add_constraint(
                    "spine_stretch",
                    module_controls,
                    module_joints[-1],
                    constraint_id=f"{module_key}_stretch_solver",
                    settings={
                        "rig_module": module_key,
                        "joint_ids": module_joints,
                        "control_ids": module_controls,
                        "stretch_control_id": pelvis_control,
                        "stretch_attribute": "stretch",
                        "rest_length": rest_length,
                        "rest_lengths": rest_lengths,
                        "measurement": "per_segment_distance",
                    },
                )
                created.append(stretch_solver)
        return self._ok(
            "rig.build_module",
            f"Built {module_key} module.",
            created_ids=created,
            data={
                "module": module_key,
                "spine_sub_shape_rotation_x": 90.0 if module_key == "spine" else None,
            },
        )

    def _build_nose_module(self, definition: CharacterDefinition) -> RiggingOperationResult:
        root_joint = definition.slots.get("NoseRoot")
        if not root_joint or root_joint not in self.graph.joints:
            raise ValueError("Character definition has no Tech Connector NoseRoot joint")
        root_name = str(self.graph.joints[root_joint].get("name") or root_joint)
        root_base = root_name[:-4] if root_name.endswith("_jnt") else root_name
        root_control = root_base + "_ctrl"
        created = []
        if root_control not in self.graph.nodes:
            result = self._op_rig_create_control({
                "target": root_joint, "control_id": root_control, "name": root_control,
                "shape": "circle", "size": 0.5, "module": "nose",
            })
            created.extend(result.created_ids)

        wanted = {"nose_upper", "nose_base", "nose_tip", "l_nostril", "r_nostril"}
        descendants = []
        pending = [root_joint]
        while pending:
            parent_joint = pending.pop(0)
            children = [
                joint_id for joint_id, joint in self.graph.joints.items()
                if str(joint.get("parent_id") or "") == parent_joint
            ]
            descendants.extend(children)
            pending.extend(children)
        for joint_id in descendants:
            joint_name = str(self.graph.joints[joint_id].get("name") or joint_id)
            base = joint_name[:-4] if joint_name.endswith("_jnt") else joint_name
            if base not in wanted:
                continue
            control = base + "_ctrl"
            if control in self.graph.nodes:
                node = self.graph.nodes[control]
                if str(node.get("dag_parent_id") or "") != root_control:
                    node["dag_parent_id"] = root_control
                continue
            result = self._op_rig_create_control({
                "target": joint_id, "control_id": control, "name": control,
                "parent": root_control, "shape": "circle", "size": 0.25, "module": "nose",
            })
            created.extend(result.created_ids)
        return self._ok(
            "rig.create_face_module", "Built nose facial module.", created_ids=created,
            data={"module": "nose", "parent": root_control},
        )

    def _build_face_module(self, module: str, definition: CharacterDefinition) -> RiggingOperationResult:
        if module == "nose":
            return self._build_nose_module(definition)
        tokens = {
            "brows": ("Brow",), "eyes": ("Eye",), "eyelids": ("Lid",),
            "mouth": ("Lip", "Jaw"), "tongue": ("Tongue",), "teeth": ("Teeth",),
            "face": ("Brow", "Eye", "Lid", "Lip", "Jaw", "Tongue", "Teeth", "Nose"),
        }[module]
        created = []
        if module == "face" and definition.slots.get("NoseRoot"):
            created.extend(self._build_nose_module(definition).created_ids)
        lip_parent = ""
        if module == "mouth":
            lip_slots = ("UpperLipCenter", "LowerLipCenter", "LeftLipCorner", "RightLipCorner")
            anchor = next((definition.slots.get(slot) for slot in lip_slots if definition.slots.get(slot)), "")
            if anchor and "lip_main_ctrl" not in self.graph.nodes:
                lip_parent = self.graph.add_node(
                    "lip_main_ctrl", "dag.control", node_id="lip_main_ctrl",
                    attributes={
                        "matrix": self._joint_world_matrix(anchor), "control_shape": "circle",
                        "control_size": 0.5, "rig_module": module, "lip_main": True,
                    },
                )
                created.append(lip_parent)
            elif "lip_main_ctrl" in self.graph.nodes:
                lip_parent = "lip_main_ctrl"
        lip_names = {
            "UpperLipCenter": "c_upper_lip_main_ctrl", "LowerLipCenter": "c_lower_lip_main_ctrl",
            "LeftLipCorner": "l_lip_corner_main_ctrl", "RightLipCorner": "r_lip_corner_main_ctrl",
        }
        for slot, joint in definition.slots.items():
            if not any(token in slot for token in tokens):
                continue
            if slot == "NoseRoot":
                continue
            control = lip_names.get(slot, f"{module}_{slot}_ctrl")
            if control in self.graph.nodes:
                continue
            result = self._op_rig_create_control({"target": joint, "control_id": control, "name": control,
                                                  "parent": lip_parent if slot in lip_names else "",
                                                  "shape": "circle", "size": 0.25, "module": module})
            created.extend(result.created_ids)
        brow_shape_rotation = None
        if module in {"brows", "face"}:
            brow_shape_rotation = 90.0
            for slot, prefix in (("LeftBrow", "l"), ("RightBrow", "r")):
                joint = definition.slots.get(slot)
                if not joint:
                    continue
                control = f"{module}_{slot}_ctrl"
                if control not in self.graph.nodes:
                    continue
                control_attributes = self.graph.nodes[control].setdefault("attributes", {})
                control_attributes.update({
                    "shape_rotation_y": 90.0,
                    "shape_rotation_space": "local_cvs",
                })
                main_control = f"{prefix}_brow_main_ctrl"
                if main_control not in self.graph.nodes:
                    self.graph.add_node(
                        main_control,
                        "dag.control",
                        node_id=main_control,
                        attributes={
                            "matrix": self._joint_world_matrix(joint),
                            "control_shape": "circle",
                            "control_size": 0.75,
                            "rig_module": module,
                            "shape_rotation_y": 90.0,
                            "shape_rotation_space": "local_cvs",
                        },
                    )
                    created.append(main_control)
                else:
                    self.graph.nodes[main_control].setdefault("attributes", {}).update({
                        "shape_rotation_y": 90.0,
                        "shape_rotation_space": "local_cvs",
                    })
                self.graph.nodes[control]["dag_parent_id"] = main_control
        return self._ok(
            "rig.create_face_module",
            f"Built {module} facial module.",
            created_ids=created,
            data={"module": module, "brow_shape_rotation_y": brow_shape_rotation},
        )

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

