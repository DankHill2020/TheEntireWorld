"""Deterministic local evaluation for provider-neutral editable rig graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - stripped DCC runtimes keep source-proxy evaluation.
    np = None


IDENTITY_MATRIX = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

LOCAL_NODE_TYPES = {
    "dag.transform",
    "dag.joint",
    "dag.control",
    "math.multiply_divide_power",
    "math.one_minus",
    "math.unit_conversion",
    "math.clamp",
    "math.condition",
    "math.sum_subtract_average",
    "math.blend",
    "logic.choice",
    "matrix.multiply",
    "matrix.inverse",
    "matrix.literal",
    "matrix.add",
    "solver.ik_rotate_plane",
    "solver.motion_path",
    "solver.ribbon_attachment",
    "utility.pose_reader",
    "animation.curve",
}
LOCAL_CONSTRAINT_TYPES = {
    "parent", "point", "orient", "rotate", "scale", "aim", "ik", "motion_path", "ribbon",
    "geometry", "normal", "tangent",
}
LOCAL_DEFORMER_TYPES = {"linear_blend_skinning", "jiggle", "flesh"}


@dataclass
class RigEvaluationResult:
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    local_matrices: dict[str, list[float]] = field(default_factory=dict)
    world_matrices: dict[str, list[float]] = field(default_factory=dict)
    evaluated_node_ids: list[str] = field(default_factory=list)
    source_proxy_node_ids: list[str] = field(default_factory=list)
    unsupported_local_node_ids: list[str] = field(default_factory=list)
    cyclic_node_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.cyclic_node_ids and not self.unsupported_local_node_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "attributes": self.attributes,
            "local_matrices": self.local_matrices,
            "world_matrices": self.world_matrices,
            "evaluated_node_ids": self.evaluated_node_ids,
            "source_proxy_node_ids": self.source_proxy_node_ids,
            "unsupported_local_node_ids": self.unsupported_local_node_ids,
            "cyclic_node_ids": self.cyclic_node_ids,
            "errors": self.errors,
        }


def rig_runtime_capabilities(graph: Any) -> dict[str, Any]:
    """Describe what can be evaluated locally without implying parity for unsupported nodes."""
    nodes = _graph_mapping(graph, "nodes")
    constraints = _graph_mapping(graph, "constraints")
    deformers = _graph_mapping(graph, "deformers")
    source_proxy_nodes = [
        node_id
        for node_id, node in nodes.items()
        if str(node.get("evaluation_mode") or "local") != "local"
    ]
    source_proxy_constraints = [
        constraint_id
        for constraint_id, item in constraints.items()
        if bool(item.get("enabled", True))
        and str(item.get("ownership") or "native") != "native"
    ]
    unsupported_nodes = sorted({
        _contract_node_type(node)
        for node_id, node in nodes.items()
        if str(node.get("evaluation_mode") or "local") == "local"
        and not _local_node_supported(node_id, node, constraints)
    })
    unsupported_constraints = sorted({
        str(item.get("type") or "opaque")
        for item in constraints.values()
        if bool(item.get("enabled", True))
        and str(item.get("ownership") or "native") == "native"
        and str(item.get("type") or "") not in LOCAL_CONSTRAINT_TYPES
    })
    source_proxy_deformers = [
        deformer_id
        for deformer_id, item in deformers.items()
        if bool(item.get("enabled", True))
        and str(item.get("evaluation_mode") or "source_proxy") not in {"gpu_local", "runtime_local"}
    ]
    unsupported_deformers = sorted({
        str(item.get("type") or "source_proxy")
        for item in deformers.values()
        if bool(item.get("enabled", True))
        and str(item.get("ownership") or "native") == "native"
        and str(item.get("type") or "") not in LOCAL_DEFORMER_TYPES
    })
    return {
        "local_node_types": sorted(LOCAL_NODE_TYPES),
        "local_constraint_types": sorted(LOCAL_CONSTRAINT_TYPES),
        "local_deformer_types": sorted(LOCAL_DEFORMER_TYPES),
        "unsupported_local_node_types": unsupported_nodes,
        "unsupported_local_constraint_types": unsupported_constraints,
        "source_proxy_node_count": len(source_proxy_nodes),
        "source_proxy_constraint_count": len(source_proxy_constraints),
        "source_proxy_deformer_count": len(source_proxy_deformers),
        "unsupported_local_deformer_types": unsupported_deformers,
        "requires_source_or_baked_evaluation": bool(
            source_proxy_nodes
            or source_proxy_constraints
            or unsupported_nodes
            or unsupported_constraints
            or source_proxy_deformers
            or unsupported_deformers
        ),
    }


def evaluate_rig_graph(graph: Any) -> RigEvaluationResult:
    """Evaluate the acyclic local DG and transform DAG with explicit unsupported-node reporting."""
    if np is None:
        raise RuntimeError("NumPy is required for local rig evaluation.")
    nodes = _graph_mapping(graph, "nodes")
    joints = _graph_mapping(graph, "joints")
    connections = _graph_mapping(graph, "connections")
    constraints = _graph_mapping(graph, "constraints")
    result = RigEvaluationResult()
    local_nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if str(node.get("evaluation_mode") or "local") == "local"
    }
    result.source_proxy_node_ids = [node_id for node_id in nodes if node_id not in local_nodes]
    result.attributes = {
        node_id: dict(node.get("attributes") or {}) for node_id, node in local_nodes.items()
    }
    result.unsupported_local_node_ids = [
        node_id
        for node_id, node in local_nodes.items()
        if not _local_node_supported(node_id, node, constraints)
    ]

    outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in local_nodes}
    indegree = {node_id: 0 for node_id in local_nodes}
    for connection in connections.values():
        if str(connection.get("connection_type") or "attribute") != "attribute":
            continue
        source_id = str(connection.get("source_node") or "")
        target_id = str(connection.get("target_node") or "")
        if source_id not in local_nodes or target_id not in local_nodes:
            continue
        outgoing[source_id].append(connection)
        if source_id != target_id:
            indegree[target_id] += 1

    queue = [node_id for node_id in local_nodes if indegree[node_id] == 0]
    for node_id in queue:
        node_type = _contract_node_type(local_nodes[node_id])
        if _local_node_supported(node_id, local_nodes[node_id], constraints):
            try:
                _evaluate_node(node_type, result.attributes[node_id])
                result.evaluated_node_ids.append(node_id)
            except Exception as exc:
                result.errors.append(f"{node_id}: {exc}")
        for connection in outgoing[node_id]:
            target_id = str(connection.get("target_node") or "")
            source_attribute = str(connection.get("source_attribute") or "")
            target_attribute = str(connection.get("target_attribute") or "")
            source_attributes = result.attributes[node_id]
            if source_attribute in source_attributes:
                result.attributes[target_id][target_attribute] = source_attributes[source_attribute]
            if target_id != node_id:
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    queue.append(target_id)
    result.cyclic_node_ids = [node_id for node_id, degree in indegree.items() if degree > 0]

    for node_id, node in local_nodes.items():
        if _contract_node_type(node) not in {"dag.transform", "dag.joint", "dag.control"}:
            continue
        joint_matrix = (joints.get(node_id) or {}).get("local_matrix")
        try:
            matrix = _local_matrix(result.attributes[node_id], joint_matrix)
            result.local_matrices[node_id] = matrix.reshape(-1).tolist()
        except Exception as exc:
            result.errors.append(f"{node_id}: {exc}")
    _rebuild_world_matrices(local_nodes, result)
    _evaluate_constraints(constraints, local_nodes, result)
    _evaluate_pose_readers(local_nodes, result)
    return result


def calculate_constraint_offset_matrix(
    current_world_matrix: list[float],
    constrained_world_matrix: list[float],
) -> list[float]:
    """Return the row-vector world offset that preserves the current pose."""
    if np is None:
        raise RuntimeError("NumPy is required for local rig evaluation.")
    current = _matrix(current_world_matrix)
    constrained = _matrix(constrained_world_matrix)
    return (current @ np.linalg.inv(constrained)).reshape(-1).tolist()


def _evaluate_node(node_type: str, attributes: dict[str, Any]) -> None:
    if node_type in {
        "dag.transform", "dag.joint", "dag.control", "solver.ik_rotate_plane",
        "solver.motion_path", "solver.ribbon_attachment", "utility.pose_reader",
    }:
        return
    if node_type == "math.multiply_divide_power":
        first = _vector(attributes, "input1", (0.0, 0.0, 0.0))
        second = _vector(attributes, "input2", (1.0, 1.0, 1.0))
        operation = attributes.get("operation", 1)
        if str(operation).lower() in {"2", "divide"}:
            output = [first[index] / second[index] if abs(second[index]) > 1.0e-12 else 0.0 for index in range(3)]
        elif str(operation).lower() in {"3", "power"}:
            output = [math.pow(first[index], second[index]) for index in range(3)]
        else:
            output = [first[index] * second[index] for index in range(3)]
        _set_vector(attributes, "output", output)
        return
    if node_type == "animation.curve":
        keys = [dict(item) for item in attributes.get("keys") or [] if isinstance(item, dict)]
        attributes["output"] = _sample_animation_curve(keys, float(attributes.get("input", 0.0) or 0.0))
        return
    if node_type == "math.one_minus":
        _set_vector(attributes, "output", [1.0 - value for value in _vector(attributes, "input", (0, 0, 0))])
        return
    if node_type == "math.unit_conversion":
        factor = float(attributes.get("conversion_factor", attributes.get("conversionFactor", 1.0)) or 0.0)
        attributes["output"] = float(attributes.get("input", 0.0) or 0.0) * factor
        return
    if node_type == "math.clamp":
        source = _vector(attributes, "input", (0, 0, 0))
        minimum = _vector(attributes, "min", (0, 0, 0))
        maximum = _vector(attributes, "max", (1, 1, 1))
        _set_vector(attributes, "output", [max(minimum[i], min(maximum[i], source[i])) for i in range(3)])
        return
    if node_type == "math.sum_subtract_average":
        values = attributes.get("inputs", attributes.get("input1D", []))
        values = [float(value) for value in (values if isinstance(values, (list, tuple)) else [values])]
        operation = str(attributes.get("operation", 1)).lower()
        if operation in {"2", "subtract"}:
            output = values[0] - sum(values[1:]) if values else 0.0
        elif operation in {"3", "average"}:
            output = sum(values) / len(values) if values else 0.0
        else:
            output = sum(values)
        attributes["output"] = output
        attributes["output1D"] = output
        return
    if node_type == "math.condition":
        first = float(attributes.get("first_term", attributes.get("firstTerm", 0.0)) or 0.0)
        second = float(attributes.get("second_term", attributes.get("secondTerm", 0.0)) or 0.0)
        operation = str(attributes.get("operation", 0)).lower()
        comparisons = {
            "0": first == second, "equal": first == second,
            "1": first != second, "not_equal": first != second,
            "2": first > second, "greater": first > second,
            "3": first >= second, "greater_equal": first >= second,
            "4": first < second, "less": first < second,
            "5": first <= second, "less_equal": first <= second,
        }
        chosen = "true_value" if comparisons.get(operation, False) else "false_value"
        fallback = "colorIfTrue" if chosen == "true_value" else "colorIfFalse"
        _set_vector(attributes, "output", _vector(attributes, chosen, _vector(attributes, fallback, (0, 0, 0))))
        return
    if node_type == "math.blend":
        first = _vector(attributes, "color1", (0, 0, 0))
        second = _vector(attributes, "color2", (0, 0, 0))
        blend = max(0.0, min(1.0, float(attributes.get("blender", 0.0) or 0.0)))
        _set_vector(attributes, "output", [(1.0 - blend) * first[i] + blend * second[i] for i in range(3)])
        return
    if node_type == "logic.choice":
        values = attributes.get("inputs", attributes.get("input", []))
        values = values if isinstance(values, (list, tuple)) else [values]
        selector = max(0, min(len(values) - 1, int(attributes.get("selector", 0) or 0))) if values else 0
        attributes["output"] = values[selector] if values else None
        return
    if node_type in {"matrix.multiply", "matrix.add"}:
        values = attributes.get("matrices", attributes.get("matrixIn", []))
        if isinstance(values, (list, tuple)) and len(values) == 16 and all(
            isinstance(value, (int, float)) for value in values
        ):
            values = [values]
        matrices = [_matrix(value) for value in values] if isinstance(values, (list, tuple)) else []
        if node_type == "matrix.add":
            output = sum(matrices, np.zeros((4, 4), dtype=np.float64)) if matrices else np.eye(4)
        else:
            output = np.eye(4)
            for matrix in matrices:
                output = output @ matrix
        attributes["output"] = output.reshape(-1).tolist()
        attributes["matrixSum"] = attributes["output"]
        return
    if node_type == "matrix.inverse":
        value = attributes.get("input", attributes.get("inputMatrix", IDENTITY_MATRIX))
        attributes["output"] = np.linalg.inv(_matrix(value)).reshape(-1).tolist()
        attributes["outputMatrix"] = attributes["output"]
        return
    if node_type == "matrix.literal":
        attributes["output"] = _matrix(attributes.get("matrix", attributes.get("output", IDENTITY_MATRIX))).reshape(-1).tolist()


def _sample_animation_curve(keys: list[dict[str, Any]], input_value: float) -> float:
    """Evaluate the portable linear/stepped subset of Maya time and driven-key curves."""
    if not keys:
        return 0.0
    ordered = sorted(keys, key=lambda item: float(item.get("frame", 0.0)))
    if input_value <= float(ordered[0].get("frame", 0.0)):
        return float(ordered[0].get("value", 0.0))
    if input_value >= float(ordered[-1].get("frame", 0.0)):
        return float(ordered[-1].get("value", 0.0))
    for first, second in zip(ordered, ordered[1:]):
        first_input = float(first.get("frame", 0.0))
        second_input = float(second.get("frame", 0.0))
        if not first_input <= input_value <= second_input:
            continue
        first_value = float(first.get("value", 0.0))
        interpolation = str(first.get("interpolation") or first.get("out_tangent") or "auto").lower()
        if interpolation in {"constant", "step", "stepnext", "stepped"}:
            return first_value
        alpha = (input_value - first_input) / max(1.0e-12, second_input - first_input)
        return first_value * (1.0 - alpha) + float(second.get("value", 0.0)) * alpha
    return float(ordered[-1].get("value", 0.0))


def _evaluate_constraints(constraints: dict[str, dict[str, Any]], nodes: dict[str, dict[str, Any]], result: RigEvaluationResult) -> None:
    for constraint_id, constraint in constraints.items():
        if not bool(constraint.get("enabled", True)):
            continue
        if str(constraint.get("ownership") or "native") != "native":
            continue
        kind = str(constraint.get("type") or "")
        if kind not in LOCAL_CONSTRAINT_TYPES:
            result.errors.append(f"{constraint_id}: local {kind or 'opaque'} constraint evaluator is unavailable")
            continue
        if kind == "ik":
            try:
                _solve_two_bone_ik(constraint, nodes, result)
            except Exception as exc:
                result.errors.append(f"{constraint_id}: {exc}")
            continue
        if kind in {"motion_path", "ribbon"}:
            try:
                _solve_surface_or_path_constraint(kind, constraint, nodes, result)
            except Exception as exc:
                result.errors.append(f"{constraint_id}: {exc}")
            continue
        if kind in {"geometry", "normal", "tangent"}:
            try:
                _solve_surface_attachment_constraint(kind, constraint, nodes, result)
            except Exception as exc:
                result.errors.append(f"{constraint_id}: {exc}")
            continue
        target_id = str(constraint.get("target_id") or "")
        source_ids = [str(value) for value in constraint.get("source_ids") or []]
        source_matrices = [result.world_matrices.get(source_id) for source_id in source_ids]
        if target_id not in result.local_matrices or not source_ids or any(value is None for value in source_matrices):
            result.errors.append(f"{constraint_id}: constraint endpoints are unavailable")
            continue
        settings = dict(constraint.get("settings") or {})
        weights = settings.get("weights") or [1.0] * len(source_ids)
        if isinstance(weights, dict):
            weights = [float(weights.get(source_id, 0.0) or 0.0) for source_id in source_ids]
        weights = np.asarray(weights, dtype=np.float64).reshape(-1)
        if len(weights) != len(source_ids) or float(weights.sum()) <= 1.0e-12:
            result.errors.append(f"{constraint_id}: constraint weights are invalid")
            continue
        weights /= weights.sum()
        current = _matrix(result.world_matrices[target_id])
        blended = _blend_matrices([_matrix(value) for value in source_matrices], weights)
        if kind == "aim":
            try:
                constrained = _solve_aim_constraint(current, blended, settings)
            except Exception as exc:
                result.errors.append(f"{constraint_id}: {exc}")
                continue
        elif kind == "point":
            constrained = current.copy()
            constrained[3, :3] = blended[3, :3]
        elif kind in {"orient", "rotate"}:
            _translation, rotation, _scale = _decompose_matrix(blended)
            translation, _old_rotation, scale = _decompose_matrix(current)
            constrained = _compose_matrix(translation, rotation, scale)
        elif kind == "scale":
            _translation, _rotation, scale = _decompose_matrix(blended)
            translation, rotation, _old_scale = _decompose_matrix(current)
            constrained = _compose_matrix(translation, rotation, scale)
        else:
            constrained = blended
        offset = settings.get("offset_matrix")
        if offset is not None:
            constrained = _matrix(offset) @ constrained
        constrained = _apply_constraint_axes(current, constrained, kind, settings.get("axes"))
        parent_id = str(nodes[target_id].get("dag_parent_id") or "")
        parent_world = _matrix(result.world_matrices[parent_id]) if parent_id in result.world_matrices else np.eye(4)
        result.local_matrices[target_id] = (constrained @ np.linalg.inv(parent_world)).reshape(-1).tolist()
        _rebuild_world_matrices(nodes, result)


def _solve_surface_attachment_constraint(
    kind: str,
    constraint: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    result: RigEvaluationResult,
) -> None:
    target_id = str(constraint.get("target_id") or "")
    if target_id not in result.local_matrices:
        raise ValueError("surface attachment target is unavailable")
    settings = dict(constraint.get("settings") or {})
    attachment = dict(settings.get("attachment") or {})
    matrix_values = attachment.get("matrix") or settings.get("surface_matrix")
    if not isinstance(matrix_values, (list, tuple)) or len(matrix_values) != 16:
        raise ValueError("surface attachment matrix is unavailable")
    current = _matrix(result.world_matrices[target_id])
    constrained = _matrix(matrix_values)
    if kind == "geometry":
        position_only = current.copy()
        position_only[3, :3] = constrained[3, :3]
        constrained = position_only
    elif kind == "tangent":
        tangent_frame = constrained.copy()
        tangent_frame[[0, 1], :3] = tangent_frame[[1, 0], :3]
        constrained = tangent_frame
    offset = settings.get("offset_matrix")
    if offset is not None:
        constrained = _matrix(offset) @ constrained
    parent_id = str(nodes[target_id].get("dag_parent_id") or "")
    parent_world = _matrix(result.world_matrices[parent_id]) if parent_id in result.world_matrices else np.eye(4)
    result.local_matrices[target_id] = (constrained @ np.linalg.inv(parent_world)).reshape(-1).tolist()
    _rebuild_world_matrices(nodes, result)


def _solve_aim_constraint(current: Any, blended_source: Any, settings: dict[str, Any]):
    target_position = current[3, :3]
    source_position = blended_source[3, :3]
    desired = source_position - target_position
    if float(np.linalg.norm(desired)) <= 1.0e-8:
        raise ValueError("Aim source and target occupy the same position")
    aim_vector = np.asarray(settings.get("aim_vector") or settings.get("aimVector") or (1.0, 0.0, 0.0), dtype=np.float64)
    if float(np.linalg.norm(aim_vector)) <= 1.0e-8:
        raise ValueError("Aim vector cannot be zero")
    aim_vector /= float(np.linalg.norm(aim_vector))
    current_direction = aim_vector @ current[:3, :3]
    world_up = np.asarray(
        settings.get("world_up_vector") or settings.get("worldUpVector")
        or settings.get("up_vector") or settings.get("upVector") or (0.0, 1.0, 0.0),
        dtype=np.float64,
    )
    desired /= float(np.linalg.norm(desired))
    desired_normal = world_up - desired * float(np.dot(world_up, desired))
    if float(np.linalg.norm(desired_normal)) <= 1.0e-8:
        fallback = np.asarray((0.0, 0.0, 1.0)) if abs(desired[2]) < 0.9 else np.asarray((0.0, 1.0, 0.0))
        desired_normal = fallback - desired * float(np.dot(fallback, desired))
    desired_normal /= max(1.0e-12, float(np.linalg.norm(desired_normal)))
    solved = _aim_bone_world_matrix(current, current_direction, desired, desired_normal)
    solved[3, :3] = target_position
    return solved


def _apply_constraint_axes(current: Any, constrained: Any, kind: str, axes: Any):
    selected = {str(axis).lower() for axis in (axes or ("x", "y", "z")) if str(axis).lower() in {"x", "y", "z"}}
    if selected == {"x", "y", "z"}:
        return constrained
    if not selected:
        return current
    old_translation, old_rotation, old_scale = _decompose_matrix(current)
    new_translation, new_rotation, new_scale = _decompose_matrix(constrained)
    if kind in {"point", "parent"}:
        new_translation = np.asarray([
            new_translation[index] if axis in selected else old_translation[index]
            for index, axis in enumerate("xyz")
        ])
    else:
        new_translation = old_translation
    if kind in {"orient", "rotate", "aim", "parent"}:
        old_euler = _euler_from_quaternion_xyz(old_rotation)
        new_euler = _euler_from_quaternion_xyz(new_rotation)
        masked_euler = [new_euler[index] if axis in selected else old_euler[index] for index, axis in enumerate("xyz")]
        new_rotation = _quaternion_from_euler(masked_euler, "xyz")
    else:
        new_rotation = old_rotation
    if kind == "scale":
        new_scale = np.asarray([
            new_scale[index] if axis in selected else old_scale[index]
            for index, axis in enumerate("xyz")
        ])
    else:
        new_scale = old_scale
    return _compose_matrix(new_translation, new_rotation, new_scale)


def _evaluate_pose_readers(nodes: dict[str, dict[str, Any]], result: RigEvaluationResult) -> None:
    for node_id, node in nodes.items():
        if _contract_node_type(node) != "utility.pose_reader":
            continue
        attributes = result.attributes.get(node_id, {})
        driver = str(attributes.get("driver") or "")
        if driver not in result.world_matrices:
            result.errors.append(f"{node_id}: pose-reader driver is unavailable")
            continue
        _translation, rotation, _scale = _decompose_matrix(_matrix(result.world_matrices[driver]))
        euler = _euler_from_quaternion_xyz(rotation)
        axis_name = str(attributes.get("axis") or "x").strip().lower()
        sign = -1.0 if axis_name.startswith("-") else 1.0
        axis = axis_name[-1:] if axis_name[-1:] in "xyz" else "x"
        angle = sign * float(euler["xyz".index(axis)])
        value_range = list(attributes.get("range") or (-90.0, 90.0))
        minimum, maximum = float(value_range[0]), float(value_range[1])
        denominator = maximum - minimum
        output = 0.0 if abs(denominator) <= 1.0e-12 else max(0.0, min(1.0, (angle - minimum) / denominator))
        attributes["angle"] = angle
        attributes["output"] = output


def _solve_two_bone_ik(constraint: dict[str, Any], nodes: dict[str, dict[str, Any]], result: RigEvaluationResult) -> None:
    settings = dict(constraint.get("settings") or {})
    start_id = str(settings.get("start_joint_id") or "")
    mid_id = str(settings.get("mid_joint_id") or "")
    end_id = str(settings.get("end_joint_id") or constraint.get("target_id") or "")
    target_id = str(settings.get("target_node_id") or "")
    pole_id = str(settings.get("pole_node_id") or "")
    required = [start_id, mid_id, end_id, target_id]
    if any(node_id not in result.world_matrices for node_id in required):
        raise ValueError("IK chain or target world matrix is unavailable")
    start_world = _matrix(result.world_matrices[start_id])
    mid_world = _matrix(result.world_matrices[mid_id])
    end_world = _matrix(result.world_matrices[end_id])
    target_world = _matrix(result.world_matrices[target_id])
    start = start_world[3, :3].copy()
    mid = mid_world[3, :3].copy()
    end = end_world[3, :3].copy()
    target = target_world[3, :3].copy()
    upper_length = float(np.linalg.norm(mid - start))
    lower_length = float(np.linalg.norm(end - mid))
    if upper_length <= 1.0e-8 or lower_length <= 1.0e-8:
        raise ValueError("IK bones must have non-zero lengths")
    target_vector = target - start
    target_distance = float(np.linalg.norm(target_vector))
    if target_distance <= 1.0e-8:
        target_vector = mid - start
        target_distance = float(np.linalg.norm(target_vector))
    direction = target_vector / max(target_distance, 1.0e-12)
    minimum = abs(upper_length - lower_length) + 1.0e-7
    maximum = upper_length + lower_length - 1.0e-7
    solved_distance = max(minimum, min(maximum, target_distance))
    solved_end = start + direction * solved_distance

    pole_position = None
    if pole_id and pole_id in result.world_matrices:
        pole_position = _matrix(result.world_matrices[pole_id])[3, :3]
    bend_reference = (pole_position - start) if pole_position is not None else (mid - start)
    bend_direction = bend_reference - direction * float(np.dot(bend_reference, direction))
    if float(np.linalg.norm(bend_direction)) <= 1.0e-8:
        start_rotation = _decompose_matrix(start_world)[1]
        secondary = _column_matrix_from_quaternion(start_rotation)[:, 1]
        bend_direction = secondary - direction * float(np.dot(secondary, direction))
    if float(np.linalg.norm(bend_direction)) <= 1.0e-8:
        fallback = np.asarray((0.0, 1.0, 0.0)) if abs(direction[1]) < 0.9 else np.asarray((0.0, 0.0, 1.0))
        bend_direction = fallback - direction * float(np.dot(fallback, direction))
    bend_direction /= max(1.0e-12, float(np.linalg.norm(bend_direction)))
    along = (
        upper_length * upper_length
        - lower_length * lower_length
        + solved_distance * solved_distance
    ) / (2.0 * solved_distance)
    height = math.sqrt(max(0.0, upper_length * upper_length - along * along))
    solved_mid = start + direction * along + bend_direction * height
    plane_normal = np.cross(direction, bend_direction)
    plane_normal /= max(1.0e-12, float(np.linalg.norm(plane_normal)))

    solved_start_world = _aim_bone_world_matrix(start_world, mid - start, solved_mid - start, plane_normal)
    solved_start_world[3, :3] = start
    solved_mid_world = _aim_bone_world_matrix(mid_world, end - mid, solved_end - solved_mid, plane_normal)
    solved_mid_world[3, :3] = solved_mid
    solved_end_world = end_world.copy()
    solved_end_world[3, :3] = solved_end
    solved_world = {
        start_id: solved_start_world,
        mid_id: solved_mid_world,
        end_id: solved_end_world,
    }
    for node_id in (start_id, mid_id, end_id):
        parent_id = str(nodes.get(node_id, {}).get("dag_parent_id") or "")
        parent_world = solved_world.get(parent_id)
        if parent_world is None and parent_id in result.world_matrices:
            parent_world = _matrix(result.world_matrices[parent_id])
        if parent_world is None:
            parent_world = np.eye(4)
        result.local_matrices[node_id] = (
            solved_world[node_id] @ np.linalg.inv(parent_world)
        ).reshape(-1).tolist()
    _rebuild_world_matrices(nodes, result)


def _solve_surface_or_path_constraint(
    kind: str,
    constraint: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    result: RigEvaluationResult,
) -> None:
    settings = dict(constraint.get("settings") or {})
    target_id = str(constraint.get("target_id") or settings.get("target_node_id") or "")
    if target_id not in result.world_matrices:
        raise ValueError(f"{kind.replace('_', ' ')} target world matrix is unavailable")
    current = _matrix(result.world_matrices[target_id])
    if kind == "motion_path":
        point, tangent = _sample_motion_path(
            settings.get("control_points") or [],
            float(settings.get("parameter", 0.0) or 0.0),
            closed=bool(settings.get("closed", False)),
        )
        normal = np.asarray(settings.get("up_vector") or (0.0, 1.0, 0.0), dtype=np.float64)
    else:
        point, tangent, normal = _sample_ribbon(
            settings.get("control_grid") or [],
            float(settings.get("u", 0.5) or 0.0),
            float(settings.get("v", 0.5) or 0.0),
        )
    constrained = current.copy()
    if bool(settings.get("follow", True)):
        current_direction = current[0, :3]
        normal = normal - tangent * float(np.dot(normal, tangent))
        if float(np.linalg.norm(normal)) <= 1.0e-8:
            fallback = np.asarray((0.0, 0.0, 1.0)) if abs(tangent[2]) < 0.9 else np.asarray((0.0, 1.0, 0.0))
            normal = fallback - tangent * float(np.dot(fallback, tangent))
        normal /= max(1.0e-12, float(np.linalg.norm(normal)))
        constrained = _aim_bone_world_matrix(current, current_direction, tangent, normal)
    constrained[3, :3] = point
    parent_id = str(nodes[target_id].get("dag_parent_id") or "")
    parent_world = _matrix(result.world_matrices[parent_id]) if parent_id in result.world_matrices else np.eye(4)
    result.local_matrices[target_id] = (constrained @ np.linalg.inv(parent_world)).reshape(-1).tolist()
    _rebuild_world_matrices(nodes, result)


def _sample_motion_path(control_points: Any, parameter: float, *, closed: bool) -> tuple[Any, Any]:
    points = np.asarray(control_points, dtype=np.float64).reshape((-1, 3))
    if len(points) < 2:
        raise ValueError("A motion path requires at least two control points")
    if closed and float(np.linalg.norm(points[0] - points[-1])) > 1.0e-12:
        points = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(lengths.sum())
    if total <= 1.0e-12:
        raise ValueError("A motion path cannot have zero length")
    value = float(parameter)
    value = value % 1.0 if closed else max(0.0, min(1.0, value))
    distance = value * total
    cumulative = np.cumsum(lengths)
    segment = min(len(lengths) - 1, int(np.searchsorted(cumulative, distance, side="right")))
    segment_start = float(cumulative[segment - 1]) if segment else 0.0
    fraction = (distance - segment_start) / max(1.0e-12, float(lengths[segment]))
    tangent = points[segment + 1] - points[segment]
    tangent /= max(1.0e-12, float(np.linalg.norm(tangent)))
    return points[segment] * (1.0 - fraction) + points[segment + 1] * fraction, tangent


def _sample_ribbon(control_grid: Any, u: float, v: float) -> tuple[Any, Any, Any]:
    grid = np.asarray(control_grid, dtype=np.float64)
    if grid.ndim != 3 or grid.shape[0] < 2 or grid.shape[1] < 2 or grid.shape[2] != 3:
        raise ValueError("A ribbon requires a rectangular control grid of at least 2 by 2 points")
    u = max(0.0, min(1.0, float(u)))
    v = max(0.0, min(1.0, float(v)))
    u_scaled = u * (grid.shape[1] - 1)
    v_scaled = v * (grid.shape[0] - 1)
    column = min(grid.shape[1] - 2, int(math.floor(u_scaled)))
    row = min(grid.shape[0] - 2, int(math.floor(v_scaled)))
    fu = u_scaled - column
    fv = v_scaled - row
    p00, p10 = grid[row, column], grid[row, column + 1]
    p01, p11 = grid[row + 1, column], grid[row + 1, column + 1]
    point = (
        p00 * (1.0 - fu) * (1.0 - fv)
        + p10 * fu * (1.0 - fv)
        + p01 * (1.0 - fu) * fv
        + p11 * fu * fv
    )
    tangent_u = (p10 - p00) * (1.0 - fv) + (p11 - p01) * fv
    tangent_v = (p01 - p00) * (1.0 - fu) + (p11 - p10) * fu
    tangent_u /= max(1.0e-12, float(np.linalg.norm(tangent_u)))
    tangent_v /= max(1.0e-12, float(np.linalg.norm(tangent_v)))
    normal = np.cross(tangent_u, tangent_v)
    if float(np.linalg.norm(normal)) <= 1.0e-8:
        raise ValueError("Ribbon tangents are degenerate")
    normal /= float(np.linalg.norm(normal))
    return point, tangent_v, normal


def _aim_bone_world_matrix(current_world: Any, current_direction: Any, desired_direction: Any, desired_normal: Any):
    translation, rotation, scale = _decompose_matrix(current_world)
    current_primary = np.asarray(current_direction, dtype=np.float64)
    current_primary /= max(1.0e-12, float(np.linalg.norm(current_primary)))
    desired_primary = np.asarray(desired_direction, dtype=np.float64)
    desired_primary /= max(1.0e-12, float(np.linalg.norm(desired_primary)))
    current_rotation = _column_matrix_from_quaternion(rotation)
    current_secondary = current_rotation[:, 1]
    current_secondary -= current_primary * float(np.dot(current_secondary, current_primary))
    if float(np.linalg.norm(current_secondary)) <= 1.0e-8:
        current_secondary = current_rotation[:, 2]
        current_secondary -= current_primary * float(np.dot(current_secondary, current_primary))
    current_secondary /= max(1.0e-12, float(np.linalg.norm(current_secondary)))
    current_normal = np.cross(current_primary, current_secondary)
    current_normal /= max(1.0e-12, float(np.linalg.norm(current_normal)))
    desired_normal = np.asarray(desired_normal, dtype=np.float64)
    desired_secondary = np.cross(desired_normal, desired_primary)
    desired_secondary /= max(1.0e-12, float(np.linalg.norm(desired_secondary)))
    current_basis = np.column_stack((current_primary, current_secondary, current_normal))
    desired_basis = np.column_stack((desired_primary, desired_secondary, desired_normal))
    delta = desired_basis @ current_basis.T
    solved_rotation = _quaternion_from_column_matrix(delta @ current_rotation)
    return _compose_matrix(translation, solved_rotation, scale)


def _rebuild_world_matrices(nodes: dict[str, dict[str, Any]], result: RigEvaluationResult) -> None:
    result.world_matrices = {}
    pending = set(result.local_matrices)
    while pending:
        progressed = False
        for node_id in list(pending):
            parent_id = str(nodes.get(node_id, {}).get("dag_parent_id") or "")
            if parent_id and parent_id in result.local_matrices and parent_id not in result.world_matrices:
                continue
            local = _matrix(result.local_matrices[node_id])
            parent_world = _matrix(result.world_matrices[parent_id]) if parent_id in result.world_matrices else np.eye(4)
            result.world_matrices[node_id] = (local @ parent_world).reshape(-1).tolist()
            pending.remove(node_id)
            progressed = True
        if not progressed:
            result.errors.append("Transform DAG could not be evaluated because its hierarchy is cyclic.")
            break


def _local_matrix(attributes: dict[str, Any], fallback: Any = None):
    matrix_value = attributes.get("matrix", fallback)
    has_trs = any(key in attributes for key in ("translate", "translateX", "rotate", "rotateX", "scale", "scaleX"))
    if matrix_value is not None and not has_trs:
        return _matrix(matrix_value)
    translation = _vector(attributes, "translate", (0, 0, 0))
    rotation = _vector(attributes, "rotate", (0, 0, 0))
    scale = _vector(attributes, "scale", (1, 1, 1))
    return _compose_matrix(translation, _quaternion_from_euler(rotation, attributes.get("rotate_order", "xyz")), scale)


def _blend_matrices(matrices: list[Any], weights: Any):
    decomposed = [_decompose_matrix(matrix) for matrix in matrices]
    translation = sum((weights[i] * decomposed[i][0] for i in range(len(matrices))), np.zeros(3))
    scale = sum((weights[i] * decomposed[i][2] for i in range(len(matrices))), np.zeros(3))
    reference = decomposed[0][1]
    quaternions = []
    for _translation, quaternion, _scale in decomposed:
        quaternions.append(-quaternion if float(np.dot(reference, quaternion)) < 0.0 else quaternion)
    rotation = sum((weights[i] * quaternions[i] for i in range(len(matrices))), np.zeros(4))
    length = float(np.linalg.norm(rotation))
    rotation = rotation / length if length > 1.0e-12 else reference
    return _compose_matrix(translation, rotation, scale)


def _decompose_matrix(matrix: Any):
    value = _matrix(matrix)
    translation = value[3, :3].copy()
    rows = value[:3, :3].copy()
    scale = np.linalg.norm(rows, axis=1)
    scale[scale < 1.0e-12] = 1.0
    rotation_row = rows / scale[:, None]
    if np.linalg.det(rotation_row) < 0.0:
        axis = int(np.argmax(np.abs(scale)))
        scale[axis] *= -1.0
        rotation_row[axis] *= -1.0
    return translation, _quaternion_from_column_matrix(rotation_row.T), scale


def _compose_matrix(translation: Any, quaternion: Any, scale: Any):
    matrix = np.eye(4, dtype=np.float64)
    rotation_row = _column_matrix_from_quaternion(quaternion).T
    matrix[:3, :3] = np.asarray(scale, dtype=np.float64)[:, None] * rotation_row
    matrix[3, :3] = np.asarray(translation, dtype=np.float64)
    return matrix


def _quaternion_from_euler(rotation_degrees: Any, order: Any = "xyz"):
    angles = {axis: math.radians(float(rotation_degrees[index])) * 0.5 for index, axis in enumerate("xyz")}
    components = {
        axis: np.asarray((math.sin(angles[axis]) if axis == "x" else 0.0,
                          math.sin(angles[axis]) if axis == "y" else 0.0,
                          math.sin(angles[axis]) if axis == "z" else 0.0,
                          math.cos(angles[axis])), dtype=np.float64)
        for axis in "xyz"
    }
    quaternion = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    for axis in str(order or "xyz").lower():
        quaternion = _quaternion_multiply(quaternion, components.get(axis, components["x"]))
    return quaternion / max(1.0e-12, float(np.linalg.norm(quaternion)))


def _euler_from_quaternion_xyz(quaternion: Any) -> list[float]:
    x, y, z, w = np.asarray(quaternion, dtype=np.float64) / max(1.0e-12, float(np.linalg.norm(quaternion)))
    sin_x = 2.0 * (w * x + y * z)
    cos_x = 1.0 - 2.0 * (x * x + y * y)
    angle_x = math.atan2(sin_x, cos_x)
    sin_y = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    angle_y = math.asin(sin_y)
    sin_z = 2.0 * (w * z + x * y)
    cos_z = 1.0 - 2.0 * (y * y + z * z)
    angle_z = math.atan2(sin_z, cos_z)
    return [math.degrees(angle_x), math.degrees(angle_y), math.degrees(angle_z)]


def _quaternion_multiply(first: Any, second: Any):
    x1, y1, z1, w1 = first
    x2, y2, z2, w2 = second
    return np.asarray((
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ), dtype=np.float64)


def _column_matrix_from_quaternion(quaternion: Any):
    x, y, z, w = np.asarray(quaternion, dtype=np.float64) / max(1.0e-12, float(np.linalg.norm(quaternion)))
    return np.asarray((
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    ), dtype=np.float64)


def _quaternion_from_column_matrix(matrix: Any):
    value = np.asarray(matrix, dtype=np.float64).reshape((3, 3))
    trace = float(np.trace(value))
    if trace > 0.0:
        root = math.sqrt(trace + 1.0) * 2.0
        quaternion = np.asarray(((value[2, 1] - value[1, 2]) / root, (value[0, 2] - value[2, 0]) / root, (value[1, 0] - value[0, 1]) / root, 0.25 * root))
    else:
        axis = int(np.argmax(np.diag(value)))
        if axis == 0:
            root = math.sqrt(max(0.0, 1.0 + value[0, 0] - value[1, 1] - value[2, 2])) * 2.0
            quaternion = np.asarray((0.25 * root, (value[0, 1] + value[1, 0]) / root, (value[0, 2] + value[2, 0]) / root, (value[2, 1] - value[1, 2]) / root))
        elif axis == 1:
            root = math.sqrt(max(0.0, 1.0 + value[1, 1] - value[0, 0] - value[2, 2])) * 2.0
            quaternion = np.asarray(((value[0, 1] + value[1, 0]) / root, 0.25 * root, (value[1, 2] + value[2, 1]) / root, (value[0, 2] - value[2, 0]) / root))
        else:
            root = math.sqrt(max(0.0, 1.0 + value[2, 2] - value[0, 0] - value[1, 1])) * 2.0
            quaternion = np.asarray(((value[0, 2] + value[2, 0]) / root, (value[1, 2] + value[2, 1]) / root, 0.25 * root, (value[1, 0] - value[0, 1]) / root))
    return quaternion / max(1.0e-12, float(np.linalg.norm(quaternion)))


def _vector(attributes: dict[str, Any], name: str, default: Any) -> list[float]:
    value = attributes.get(name)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        components = [float(value[0]), float(value[1]), float(value[2])]
    else:
        components = [float(default[index]) for index in range(3)]
    suffixes = ("X", "Y", "Z")
    return [
        float(attributes[name + suffix]) if name + suffix in attributes else components[index]
        for index, suffix in enumerate(suffixes)
    ]


def _set_vector(attributes: dict[str, Any], name: str, values: Any) -> None:
    vector = [float(value) for value in values]
    attributes[name] = vector
    for suffix, value in zip(("X", "Y", "Z"), vector):
        attributes[name + suffix] = value


def _matrix(value: Any):
    source = value if value is not None else IDENTITY_MATRIX
    array = np.asarray(source, dtype=np.float64)
    if array.size != 16:
        raise ValueError("A rig matrix must contain 16 values.")
    return array.reshape((4, 4)).copy()


def _graph_mapping(graph: Any, name: str) -> dict[str, dict[str, Any]]:
    value = getattr(graph, name, None)
    if value is None and isinstance(graph, dict):
        value = graph.get(name)
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {str(item.get("id") or item.get("native_id") or index): item for index, item in enumerate(value) if isinstance(item, dict)}
    return {}


def _local_node_supported(
    node_id: str,
    node: dict[str, Any],
    constraints: dict[str, dict[str, Any]],
) -> bool:
    node_type = _contract_node_type(node)
    if node_type not in LOCAL_NODE_TYPES:
        return False
    if node_type in {"solver.ik_rotate_plane", "solver.motion_path", "solver.ribbon_attachment"}:
        solver = constraints.get(str(node_id)) or {}
        expected = {
            "solver.ik_rotate_plane": "ik",
            "solver.motion_path": "motion_path",
            "solver.ribbon_attachment": "ribbon",
        }[node_type]
        return str(solver.get("type") or "") == expected and bool(solver.get("settings"))
    return True


def _contract_node_type(node: dict[str, Any]) -> str:
    """Return the neutral evaluator contract behind a TC-native node class."""
    return str(node.get("contract_node_type") or node.get("node_type") or "")
