"""Portable mechanical relationships authored in the editable rig graph."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


MECHANICAL_RIG_SCHEMA = "tech_connector.mechanical_rig.v1"
MECHANICAL_MODES = frozenset({"gear", "rack_pinion", "pulley", "piston", "hydraulic", "hinge"})


@dataclass(frozen=True)
class MechanicalRigResult:
    mode: str
    driver: str
    driven: str
    created_node_ids: tuple[str, ...] = ()
    created_connection_ids: tuple[str, ...] = ()
    created_constraint_ids: tuple[str, ...] = ()
    schema: str = MECHANICAL_RIG_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_mechanical_rig(
    graph: Any,
    *,
    mode: str,
    driver: str,
    driven: str,
    driver_axis: str = "y",
    driven_axis: str = "y",
    ratio: float | None = None,
    module: str = "mechanical",
    bidirectional_aim: bool = False,
) -> MechanicalRigResult:
    kind = str(mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    if kind not in MECHANICAL_MODES:
        raise ValueError("Mechanical mode must be gear, rack_pinion, pulley, piston, hydraulic, or hinge.")
    driver_id = str(driver or "")
    driven_id = str(driven or "")
    if driver_id not in getattr(graph, "nodes", {}) or driven_id not in getattr(graph, "nodes", {}):
        raise KeyError("Mechanical driver and driven IDs must resolve in the editable rig graph.")
    if driver_id == driven_id:
        raise ValueError("Mechanical driver and driven nodes must be different.")
    source_axis = _axis(driver_axis)
    target_axis = _axis(driven_axis)
    module_id = str(module or "mechanical")

    if kind in {"gear", "rack_pinion", "pulley"}:
        default_ratio = -1.0 if kind == "gear" else 1.0
        multiplier = float(default_ratio if ratio is None else ratio)
        if abs(multiplier) <= 1.0e-12:
            raise ValueError("Mechanical ratio cannot be zero.")
        node_id = _unique_id(graph.nodes, f"{module_id}_{kind}_ratio")
        graph.add_node(
            node_id,
            "math.multiply_divide_power",
            node_id=node_id,
            attributes={
                "operation": "multiply",
                "input1": [0.0, 0.0, 0.0],
                "input2": [multiplier, multiplier, multiplier],
                "mechanical_mode": kind,
                "ratio": multiplier,
                "rig_module": module_id,
            },
        )
        source_attribute = ("translate" if kind == "pulley" else "rotate") + source_axis.upper()
        target_attribute = ("translate" if kind == "rack_pinion" else "rotate") + target_axis.upper()
        input_attribute = "input1" + target_axis.upper()
        output_attribute = "output" + target_axis.upper()
        first = graph.connect_attributes(driver_id, source_attribute, node_id, input_attribute)
        second = graph.connect_attributes(node_id, output_attribute, driven_id, target_attribute)
        return MechanicalRigResult(kind, driver_id, driven_id, (node_id,), (first, second))

    if kind in {"piston", "hydraulic"}:
        settings = {
            "aim_vector": _axis_vector(target_axis),
            "up_vector": [0.0, 1.0, 0.0] if target_axis != "y" else [0.0, 0.0, 1.0],
            "world_up_vector": [0.0, 1.0, 0.0] if target_axis != "y" else [0.0, 0.0, 1.0],
            "mechanical_mode": kind,
            "rig_module": module_id,
        }
        constraints = [graph.add_constraint("aim", [driver_id], driven_id, settings=settings)]
        if bidirectional_aim:
            reverse_settings = {**settings, "aim_vector": _axis_vector(source_axis)}
            constraints.append(graph.add_constraint("aim", [driven_id], driver_id, settings=reverse_settings))
        return MechanicalRigResult(kind, driver_id, driven_id, created_constraint_ids=tuple(constraints))

    constraint = graph.add_constraint(
        "orient",
        [driver_id],
        driven_id,
        settings={"axes": [target_axis], "mechanical_mode": kind, "rig_module": module_id},
    )
    return MechanicalRigResult(kind, driver_id, driven_id, created_constraint_ids=(constraint,))


def _axis(value: str) -> str:
    axis = str(value or "y").strip().lower().lstrip("+-")
    if axis not in {"x", "y", "z"}:
        raise ValueError("Mechanical axes must be x, y, or z.")
    return axis


def _axis_vector(axis: str) -> list[float]:
    return [1.0 if axis == value else 0.0 for value in "xyz"]


def _unique_id(existing: dict[str, Any], base: str) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


__all__ = ["MECHANICAL_MODES", "MECHANICAL_RIG_SCHEMA", "MechanicalRigResult", "create_mechanical_rig"]
