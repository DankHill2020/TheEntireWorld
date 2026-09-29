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
from tech_connector.game_engine.deformation.muscle import (
    MuscleDeformerSettings,
    MuscleRuntimeState,
    PoseSpaceTissueDriver,
    evaluate_muscle,
)
from tech_connector.game_engine.deformation.blend_shape import (
    BlendShapeTelemetry,
    blend_shape_target_from_dict,
    evaluate_blend_shape,
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
    backend: str = "reference_cpu"
    provider_id: str = ""
    memory_bytes: int = 0
    lod_quality: float = 1.0
    budget_pressure: float = 0.0
    resident_output: bool = False
    synchronization_points: int = 0
    readback_deferred: bool = False
    reused_states: int = 0
    state_count: int = 0
    muscle_activation: dict[str, dict[str, float | int]] = field(default_factory=dict)
    teleport_resets: int = 0
    blend_shapes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mesh_id": self.mesh_id,
            "evaluated_deformers": list(self.evaluated_deformers),
            "skipped_deformers": list(self.skipped_deformers),
            "collision_contacts": self.collision_contacts,
            "settled_vertices": self.settled_vertices,
            "deformer_ms": dict(self.deformer_ms),
            "evaluation_ms": self.evaluation_ms,
            "backend": self.backend, "provider_id": self.provider_id,
            "memory_bytes": self.memory_bytes, "lod_quality": self.lod_quality,
            "budget_pressure": self.budget_pressure, "resident_output": self.resident_output,
            "synchronization_points": self.synchronization_points,
            "readback_deferred": self.readback_deferred,
            "reused_states": self.reused_states, "state_count": self.state_count,
            "muscle_activation": dict(self.muscle_activation),
            "teleport_resets": self.teleport_resets,
            "blend_shapes": dict(self.blend_shapes),
        }


@dataclass
class DeformationStackRuntime:
    jiggle_states: dict[str, JiggleRuntimeState] = field(default_factory=dict)
    flesh_states: dict[str, FleshRuntimeState] = field(default_factory=dict)
    muscle_states: dict[str, MuscleRuntimeState] = field(default_factory=dict)
    gpu_states: dict[str, Any] = field(default_factory=dict)
    gpu_lod_controllers: dict[str, Any] = field(default_factory=dict)

    def reset(self, deformer_id: str = "") -> None:
        if deformer_id:
            self.jiggle_states.pop(str(deformer_id), None)
            self.flesh_states.pop(str(deformer_id), None)
            self.muscle_states.pop(str(deformer_id), None)
            self.gpu_states.pop(str(deformer_id), None)
        else:
            self.jiggle_states.clear()
            self.flesh_states.clear()
            self.muscle_states.clear()
            self.gpu_states.clear()
            self.gpu_lod_controllers.clear()

    def evaluate_gpu(
        self,
        rig_graph: Any,
        mesh_id: str,
        upstream_positions: Sequence[Sequence[float]],
        dt: float,
        *,
        provider_id: str = "cupy_cuda",
        target_ms: float = 4.0,
        edges: Sequence[Sequence[int]] = (),
        normals: Sequence[Sequence[float]] = (),
        colliders: Sequence[Mapping[str, Any]] = (),
        resident_output: bool = False,
    ) -> tuple[Any, DeformationStackTelemetry]:
        """Evaluate the ordered blend-shape/muscle/jiggle/flesh stack without inter-deformer readback."""
        from tech_connector.game_engine.deformation.tc_deformation_gpu_service import (
            DeformationLodController,
            evaluate_gpu_deformation_stack,
        )

        key = str(mesh_id)
        controller = self.gpu_lod_controllers.setdefault(
            key, DeformationLodController(target_ms=max(0.01, float(target_ms))),
        )
        controller.target_ms = max(0.01, float(target_ms))
        result, metrics = evaluate_gpu_deformation_stack(
            rig_graph, key, upstream_positions, dt, provider_id=provider_id,
            states=self.gpu_states, lod=controller, edges=edges, normals=normals,
            colliders=colliders, resident_output=resident_output,
        )
        telemetry = DeformationStackTelemetry(
            key,
            evaluated_deformers=list(metrics["evaluated_deformers"]),
            skipped_deformers=list(metrics["skipped_deformers"]),
            collision_contacts=int(metrics["collision_contacts"]),
            settled_vertices=int(metrics["settled_vertices"]),
            deformer_ms=dict(metrics["deformer_ms"]),
            evaluation_ms=float(metrics["evaluation_ms"]),
            backend="gpu_compute", provider_id=provider_id,
            memory_bytes=int(metrics["memory_bytes"]),
            lod_quality=float(metrics["lod_quality"]),
            budget_pressure=float(metrics["budget_pressure"]),
            resident_output=bool(metrics["resident_output"]),
            synchronization_points=int(metrics["synchronization_points"]),
            readback_deferred=bool(metrics["readback_deferred"]),
            reused_states=int(metrics["reused_states"]),
            state_count=int(metrics["state_count"]),
            muscle_activation=dict(metrics.get("muscle_activation") or {}),
            teleport_resets=int(metrics.get("teleport_resets", 0)),
            blend_shapes=dict(metrics.get("blend_shapes") or {}),
        )
        return result, telemetry

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
            if kind == "blend_shape":
                stats = BlendShapeTelemetry()
                result = evaluate_blend_shape(
                    result, [blend_shape_target_from_dict(item) for item in settings.get("targets", ())],
                    weights=dict(settings.get("weights") or {}),
                    driver_values=dict(settings.get("driver_values") or {}),
                    frame=settings.get("frame"), telemetry=stats,
                )
                telemetry.blend_shapes[identifier] = {
                    "active_targets": stats.active_targets, "active_deltas": stats.active_deltas,
                    "maximum_absolute_weight": stats.maximum_absolute_weight,
                    "resolved_weights": dict(stats.resolved_weights),
                }
                telemetry.evaluated_deformers.append(identifier)
                telemetry.deformer_ms[identifier] = (time.perf_counter() - deformer_started) * 1000.0
                continue
            influence_data = settings.get("influence_map")
            if not isinstance(influence_data, dict):
                telemetry.skipped_deformers.append(identifier)
                continue
            influence = DeformationWeightMap.from_dict(influence_data)
            if len(influence.values) != len(result):
                telemetry.skipped_deformers.append(identifier)
                continue
            if kind == "muscle":
                values = MuscleDeformerSettings(**dict(settings.get("muscle") or {})).validated()
                state = self.muscle_states.setdefault(identifier, MuscleRuntimeState())
                activation_data = settings.get("activation_map") or influence_data
                activation_map = DeformationWeightMap.from_dict(dict(activation_data))
                drivers = [PoseSpaceTissueDriver(**dict(item)).validated() for item in settings.get("pose_drivers", ())]
                result = evaluate_muscle(
                    result, activation_map, state, values, dt,
                    activation=settings.get("activation", 1.0), normals=normals,
                    pose_drivers=drivers, pose_values=dict(settings.get("pose_values") or {}),
                    pose_maps=dict(settings.get("pose_maps") or {}),
                )
                telemetry.muscle_activation[identifier] = {
                    "mean": state.activation_mean, "maximum": state.activation_max,
                    "active_vertices": state.activated_vertices,
                    "kinetic_energy": state.kinetic_energy,
                }
                telemetry.teleport_resets += state.teleport_count
            elif kind == "jiggle":
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
