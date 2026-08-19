"""Ordered runtime evaluation for portable skin-adjacent secondary deformers."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Mapping, Sequence

from tech_connector.game_engine.deformation.flesh import (
    FleshDeformerSettings,
    FleshRuntimeState,
    evaluate_flesh,
)
from tech_connector.game_engine.deformation.jiggle import (
    JiggleDeformerSettings,
    JiggleRuntimeState,
    evaluate_jiggle,
)
from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap, Vec3


@dataclass
class DeformationStackTelemetry:
    mesh_id: str
    evaluated_deformers: list[str] = field(default_factory=list)
    skipped_deformers: list[str] = field(default_factory=list)
    collision_contacts: int = 0
    settled_vertices: int = 0
    deformer_ms: dict[str, float] = field(default_factory=dict)
    evaluation_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mesh_id": self.mesh_id,
            "evaluated_deformers": list(self.evaluated_deformers),
            "skipped_deformers": list(self.skipped_deformers),
            "collision_contacts": self.collision_contacts,
            "settled_vertices": self.settled_vertices,
            "deformer_ms": dict(self.deformer_ms),
            "evaluation_ms": self.evaluation_ms,
        }


@dataclass
class DeformationStackRuntime:
    jiggle_states: dict[str, JiggleRuntimeState] = field(default_factory=dict)
    flesh_states: dict[str, FleshRuntimeState] = field(default_factory=dict)

    def reset(self, deformer_id: str = "") -> None:
        if deformer_id:
            self.jiggle_states.pop(str(deformer_id), None)
            self.flesh_states.pop(str(deformer_id), None)
        else:
            self.jiggle_states.clear()
            self.flesh_states.clear()

    def evaluate(
        self,
        rig_graph: Any,
        mesh_id: str,
        upstream_positions: Sequence[Sequence[float]],
        dt: float,
        *,
        edges: Sequence[Sequence[int]] = (),
        normals: Sequence[Sequence[float]] = (),
        colliders: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[list[Vec3], DeformationStackTelemetry]:
        """Evaluate supported deformers in graph order after canonical skinning."""
        started = time.perf_counter()
        result = [_vec3(value) for value in upstream_positions]
        telemetry = DeformationStackTelemetry(str(mesh_id))
        deformers = sorted(
            (
                (str(identifier), item)
                for identifier, item in (getattr(rig_graph, "deformers", {}) or {}).items()
                if str(item.get("mesh_id") or "") == str(mesh_id) and bool(item.get("enabled", True))
            ),
            key=lambda pair: (int(pair[1].get("order", 0) or 0), pair[0]),
        )
        for identifier, deformer in deformers:
            deformer_started = time.perf_counter()
            kind = str(deformer.get("type") or "")
            settings = dict(deformer.get("settings") or {})
            influence_data = settings.get("influence_map")
            if not isinstance(influence_data, dict):
                telemetry.skipped_deformers.append(identifier)
                continue
            influence = DeformationWeightMap.from_dict(influence_data)
            if len(influence.values) != len(result):
                telemetry.skipped_deformers.append(identifier)
                continue
            if kind == "jiggle":
                values = JiggleDeformerSettings(**dict(settings.get("jiggle") or {})).validated()
                state = self.jiggle_states.setdefault(identifier, JiggleRuntimeState())
                result = evaluate_jiggle(result, influence, state, values, dt, colliders=colliders)
                telemetry.collision_contacts += state.collision_count
                telemetry.settled_vertices += state.settled_vertex_count
            elif kind == "flesh":
                values = FleshDeformerSettings(**dict(settings.get("flesh") or {})).validated()
                state = self.flesh_states.setdefault(identifier, FleshRuntimeState())
                result = evaluate_flesh(
                    result, influence, state, values, dt,
                    edges=edges, normals=normals, colliders=colliders,
                )
                telemetry.collision_contacts += state.collision_count
            else:
                telemetry.skipped_deformers.append(identifier)
                continue
            telemetry.evaluated_deformers.append(identifier)
            telemetry.deformer_ms[identifier] = (time.perf_counter() - deformer_started) * 1000.0
        telemetry.evaluation_ms = (time.perf_counter() - started) * 1000.0
        return result, telemetry


def _vec3(value: Sequence[float]) -> Vec3:
    values = tuple(float(item) for item in value)
    return (values + (0.0, 0.0, 0.0))[:3]


__all__ = ["DeformationStackRuntime", "DeformationStackTelemetry"]
