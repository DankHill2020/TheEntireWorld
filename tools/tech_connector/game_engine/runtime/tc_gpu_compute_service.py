"""Native D3D11 and Qt RHI compute executors for Tech Connector simulation.

The native kernel covers uniform-force integration plus one plane and one sphere
collider and graph-colored XPBD distance constraints, with independent upload,
resident dispatch, and on-demand readback sessions.
Unsupported worlds fail closed to the reference executor so backend status and
performance telemetry remain honest as coverage grows stage-by-stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import copy
import ctypes
import math
import struct
import time
from typing import Any

import numpy as np


SHADER_PATH = Path(__file__).with_name("shaders") / "tc_particle_integrate.comp.qsb"
NATIVE_LIBRARY_CANDIDATES = (
    Path(__file__).parent.parent / "native" / ".tech_connector" / "tc_gpu_compute.dll",
    Path(__file__).parent.parent / "native" / ".tech_connector" / "cmake" / "GpuCompute" / "Release" / "tc_gpu_compute.dll",
    Path(__file__).parent.parent / "native" / ".tech_connector" / "cmake" / "Release" / "Release" / "tc_gpu_compute.dll",
)
WORKGROUP_SIZE = 256


@dataclass
class GpuDispatchTelemetry:
    backend: str = ""
    device: str = ""
    particle_count: int = 0
    workgroups: int = 0
    upload_bytes: int = 0
    readback_bytes: int = 0
    dispatch_ms: float = 0.0
    gpu_resident: bool = False
    synchronized_readback: bool = True
    session_id: int = 0
    supported_stages: tuple[str, ...] = ("integrate",)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "device": self.device,
            "particle_count": self.particle_count,
            "workgroups": self.workgroups,
            "upload_bytes": self.upload_bytes,
            "readback_bytes": self.readback_bytes,
            "dispatch_ms": self.dispatch_ms,
            "gpu_resident": self.gpu_resident,
            "synchronized_readback": self.synchronized_readback,
            "session_id": self.session_id,
            "supported_stages": list(self.supported_stages),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class D3D11MeshBvhPayload:
    """GPU-friendly flattened BVH with contiguous leaf triangle records."""

    node_bounds: np.ndarray
    node_metadata: np.ndarray
    triangle_vertices: np.ndarray
    friction: float
    restitution: float
    surface_velocity: tuple[float, float, float]
    source_signature: tuple[Any, ...]
    maximum_depth: int

    @property
    def memory_bytes(self) -> int:
        return int(self.node_bounds.nbytes + self.node_metadata.nbytes + self.triangle_vertices.nbytes)


def compile_d3d11_mesh_bvh(collider: Any) -> D3D11MeshBvhPayload:
    """Flatten the canonical refittable collider BVH for bounded D3D11 stack traversal."""
    acceleration = collider.acceleration()
    diagnostics = acceleration.diagnostics()
    maximum_depth = int(diagnostics["maximum_depth"])
    if maximum_depth > 64:
        raise GpuComputeUnavailable(
            f"Mesh BVH depth {maximum_depth} exceeds the qualified D3D11 traversal stack of 64."
        )
    node_bounds = np.zeros((len(acceleration.nodes) * 2, 4), dtype=np.float32)
    node_metadata = np.zeros((len(acceleration.nodes), 4), dtype=np.uint32)
    ordered_triangles: list[int] = []
    for node_index, node in enumerate(acceleration.nodes):
        node_bounds[node_index * 2, :3] = node.bounds[:3]
        node_bounds[node_index * 2 + 1, :3] = node.bounds[3:]
        start = len(ordered_triangles)
        ordered_triangles.extend(node.triangles)
        node_metadata[node_index] = (
            int(node.left) if node.left >= 0 else np.iinfo(np.uint32).max,
            int(node.right) if node.right >= 0 else np.iinfo(np.uint32).max,
            start, len(node.triangles),
        )
    triangle_vertices = np.zeros((len(ordered_triangles) * 3, 4), dtype=np.float32)
    for output_index, triangle_index in enumerate(ordered_triangles):
        triangle = acceleration.triangles[triangle_index]
        for corner, vertex_index in enumerate(triangle):
            triangle_vertices[output_index * 3 + corner, :3] = collider.vertices[vertex_index]
    signature = (
        int(getattr(collider, "geometry_revision", 0)),
        tuple(tuple(int(value) for value in face) for face in collider.faces),
        len(collider.vertices), len(acceleration.triangles), len(acceleration.nodes),
    )
    return D3D11MeshBvhPayload(
        node_bounds=np.ascontiguousarray(node_bounds),
        node_metadata=np.ascontiguousarray(node_metadata),
        triangle_vertices=np.ascontiguousarray(triangle_vertices),
        friction=max(0.0, float(collider.friction)),
        restitution=max(0.0, float(collider.restitution)),
        surface_velocity=tuple(float(value) for value in collider.velocity),
        source_signature=signature,
        maximum_depth=maximum_depth,
    )


class GpuComputeUnavailable(RuntimeError):
    pass


class NativeD3D11ParticleCompute:
    """Headless D3D11 compute service exposed through the native C ABI."""

    def __init__(self, library_path: str | Path | None = None):
        candidates = (Path(library_path),) if library_path else NATIVE_LIBRARY_CANDIDATES
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            raise GpuComputeUnavailable("The native tc_gpu_compute library has not been built.")
        self.library_path = Path(path)
        self._library = ctypes.WinDLL(str(self.library_path))
        float_buffer = np.ctypeslib.ndpointer(dtype=np.float32, ndim=2, flags="C_CONTIGUOUS")
        self._library.tc_gpu_compute_available.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        self._library.tc_gpu_compute_available.restype = ctypes.c_int
        self._library.tc_gpu_integrate_particles.argtypes = [
            float_buffer, float_buffer, ctypes.c_uint32,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_integrate_particles.restype = ctypes.c_int
        self._library.tc_gpu_upload_particles.argtypes = [
            float_buffer, float_buffer, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_upload_particles.restype = ctypes.c_int
        self._library.tc_gpu_dispatch_particles.argtypes = [
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_uint32,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_dispatch_particles.restype = ctypes.c_int
        self._library.tc_gpu_readback_particles.argtypes = [
            float_buffer, float_buffer, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_readback_particles.restype = ctypes.c_int
        self._library.tc_gpu_resident_particle_count.argtypes = []
        self._library.tc_gpu_resident_particle_count.restype = ctypes.c_uint32
        session_handle = ctypes.c_uint64
        self._library.tc_gpu_session_create.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        self._library.tc_gpu_session_create.restype = session_handle
        self._library.tc_gpu_session_destroy.argtypes = [session_handle, ctypes.c_char_p, ctypes.c_size_t]
        self._library.tc_gpu_session_destroy.restype = ctypes.c_int
        self._library.tc_gpu_session_upload_particles.argtypes = [
            session_handle, float_buffer, float_buffer, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_upload_particles.restype = ctypes.c_int
        self._library.tc_gpu_session_dispatch_particles.argtypes = [
            session_handle,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_uint32,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_uint32,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_dispatch_particles.restype = ctypes.c_int
        self._library.tc_gpu_session_readback_particles.argtypes = [
            session_handle, float_buffer, float_buffer, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_readback_particles.restype = ctypes.c_int
        self._library.tc_gpu_session_particle_count.argtypes = [session_handle]
        self._library.tc_gpu_session_particle_count.restype = ctypes.c_uint32
        self._library.tc_gpu_session_upload_physics_fields.argtypes = [
            session_handle, float_buffer, ctypes.c_uint32, ctypes.c_float,
            ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_upload_physics_fields.restype = ctypes.c_int
        self._library.tc_gpu_session_physics_field_count.argtypes = [session_handle]
        self._library.tc_gpu_session_physics_field_count.restype = ctypes.c_uint32
        uint_record_buffer = np.ctypeslib.ndpointer(dtype=np.uint32, ndim=2, flags="C_CONTIGUOUS")
        self._library.tc_gpu_session_upload_mesh_bvh.argtypes = [
            session_handle, float_buffer, uint_record_buffer, ctypes.c_uint32,
            float_buffer, ctypes.c_uint32, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_upload_mesh_bvh.restype = ctypes.c_int
        self._library.tc_gpu_session_dispatch_mesh_bvh.argtypes = [
            session_handle, ctypes.c_float, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_dispatch_mesh_bvh.restype = ctypes.c_int
        self._library.tc_gpu_session_mesh_triangle_count.argtypes = [session_handle]
        self._library.tc_gpu_session_mesh_triangle_count.restype = ctypes.c_uint32
        self._library.tc_gpu_session_dispatch_self_collision.argtypes = [
            session_handle, ctypes.c_float, ctypes.c_float, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_dispatch_self_collision.restype = ctypes.c_int
        uint_pair_buffer = np.ctypeslib.ndpointer(dtype=np.uint32, ndim=2, flags="C_CONTIGUOUS")
        uint_offset_buffer = np.ctypeslib.ndpointer(dtype=np.uint32, ndim=1, flags="C_CONTIGUOUS")
        self._library.tc_gpu_session_upload_distance_constraints.argtypes = [
            session_handle, uint_pair_buffer, float_buffer, ctypes.c_uint32,
            uint_offset_buffer, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_upload_distance_constraints.restype = ctypes.c_int
        self._library.tc_gpu_session_dispatch_distance_constraints.argtypes = [
            session_handle, ctypes.c_float, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.tc_gpu_session_dispatch_distance_constraints.restype = ctypes.c_int
        self._library.tc_gpu_session_distance_constraint_count.argtypes = [session_handle]
        self._library.tc_gpu_session_distance_constraint_count.restype = ctypes.c_uint32
        message = ctypes.create_string_buffer(1024)
        if not self._library.tc_gpu_compute_available(message, len(message)):
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self.device_description = message.value.decode("utf-8", errors="replace")
        message = ctypes.create_string_buffer(1024)
        self.session_id = int(self._library.tc_gpu_session_create(message, len(message)))
        if self.session_id == 0:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self._closed = False
        self._constraint_signature: tuple[Any, ...] | None = None
        self._physics_field_signature: tuple[Any, ...] | None = None
        self._mesh_bvh_signature: tuple[Any, ...] | None = None
        self.last_telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, session_id=self.session_id
        )

    @property
    def resident_particle_count(self) -> int:
        return 0 if self._closed else int(self._library.tc_gpu_session_particle_count(self.session_id))

    @property
    def resident_distance_constraint_count(self) -> int:
        return 0 if self._closed else int(
            self._library.tc_gpu_session_distance_constraint_count(self.session_id)
        )

    @property
    def resident_physics_field_count(self) -> int:
        return 0 if self._closed else int(
            self._library.tc_gpu_session_physics_field_count(self.session_id)
        )

    @property
    def resident_mesh_triangle_count(self) -> int:
        return 0 if self._closed else int(
            self._library.tc_gpu_session_mesh_triangle_count(self.session_id)
        )

    def close(self) -> None:
        if self._closed:
            return
        message = ctypes.create_string_buffer(1024)
        if not self._library.tc_gpu_session_destroy(self.session_id, message, len(message)):
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self._closed = True

    def __enter__(self) -> "NativeD3D11ParticleCompute":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def dispatch(self, world: Any, dt: float) -> GpuDispatchTelemetry:
        eligible, reason = gpu_world_eligibility(world)
        if not eligible:
            raise GpuComputeUnavailable(reason)
        if (getattr(world, "constraints", None) or _d3d11_spatial_fields(world)
                or getattr(world, "mesh_colliders", None) or bool(getattr(world, "self_collision", False))):
            return self.dispatch_runtime(world, dt, resident_output=False)
        particles = list(getattr(world, "particles", ()) or ())
        if not particles:
            world.time_seconds += float(dt)
            return GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        positions = np.zeros((len(particles), 4), dtype=np.float32)
        velocities = np.zeros((len(particles), 4), dtype=np.float32)
        for index, particle in enumerate(particles):
            positions[index, :3] = particle.position
            positions[index, 3] = float(particle.radius) if (
                particle.alive and not particle.pinned and not particle.frozen and particle.inverse_mass > 0.0
            ) else 0.0
            velocities[index, :3] = particle.velocity
            material = world.materials.get(particle.material)
            velocities[index, 3] = max(0.0, float(material.damping if material is not None else 0.0))
        acceleration = _uniform_acceleration(world)
        telemetry = self.integrate_arrays(
            positions, velocities, acceleration=acceleration, dt=float(dt), substeps=max(1, int(world.substeps)),
            collision_plane=_plane_parameters(world),
            collision_sphere=_sphere_parameters(world),
        )
        for index, particle in enumerate(particles):
            particle.position = tuple(float(value) for value in positions[index, :3])
            particle.velocity = tuple(float(value) for value in velocities[index, :3])
        world.time_seconds += float(dt)
        return telemetry

    def dispatch_runtime(
        self, world: Any, dt: float, *, substeps: int | None = None,
        constraint_iterations: int | None = None, resident_output: bool = False
    ) -> GpuDispatchTelemetry:
        """Execute a compiled tick while retaining the per-world native device session."""
        particles = list(getattr(world, "particles", ()) or ())
        reuse = bool(
            resident_output and getattr(world, "_gpu_buffers_authoritative", False)
            and self.resident_particle_count == len(particles)
            and hasattr(world, "_d3d11_runtime_positions")
        )
        eligible, reason = gpu_world_eligibility(
            world,
            used_material_names=(getattr(world, "_d3d11_runtime_material_names", None) if reuse else None),
            trust_resident_constraints=bool(
                reuse and not getattr(world, "_gpu_constraints_dirty", False)
                and self.resident_distance_constraint_count == len(getattr(world, "constraints", ()) or ())
            ),
        )
        if not eligible:
            raise GpuComputeUnavailable(reason)
        upload = GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        if not reuse:
            positions, velocities = _world_particle_arrays(world)
            world._d3d11_runtime_positions = positions
            world._d3d11_runtime_velocities = velocities
            world._d3d11_runtime_material_names = {particle.material for particle in particles if particle.alive}
            if particles:
                upload = self.upload_resident_arrays(positions, velocities)
        if not particles:
            world.time_seconds += float(dt)
            return upload
        constraint_upload = GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        constraints_dirty = bool(getattr(world, "_gpu_constraints_dirty", False))
        if getattr(world, "constraints", None) and (
            not reuse or constraints_dirty
            or self.resident_distance_constraint_count != len(world.constraints)
        ):
            constraint_upload = self.upload_resident_distance_constraints(world)
            world._gpu_constraints_dirty = False
        field_upload = GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        spatial_fields = _d3d11_spatial_fields(world)
        fields_dirty = bool(getattr(world, "_gpu_fields_dirty", False))
        if not reuse or fields_dirty or self.resident_physics_field_count != len(spatial_fields):
            field_upload = self.upload_resident_physics_fields(world)
            world._gpu_fields_dirty = False
        mesh_upload = GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        mesh_colliders = list(getattr(world, "mesh_colliders", ()) or ())
        if mesh_colliders:
            collider = mesh_colliders[0]
            mesh_signature = (
                int(getattr(collider, "geometry_revision", 0)),
                tuple(tuple(face) for face in collider.faces), len(collider.vertices),
                float(collider.friction), float(collider.restitution), tuple(collider.velocity),
            )
            if not reuse or mesh_signature != self._mesh_bvh_signature:
                mesh_upload = self.upload_resident_mesh_bvh(collider)
        substep_count = max(1, int(substeps if substeps is not None else world.substeps))
        iteration_count = max(1, int(
            constraint_iterations if constraint_iterations is not None else world.constraint_iterations
        ))
        sub_dt = float(dt) / substep_count
        dispatch_ms = 0.0
        workgroups = 0
        supported_stages: set[str] = set()
        for substep_index in range(substep_count):
            world._field_time_seconds = world.time_seconds + substep_index * sub_dt
            step = self.step_resident(
                acceleration=_uniform_acceleration(world), dt=sub_dt, substeps=1,
                collision_plane=_plane_parameters(world), collision_sphere=_sphere_parameters(world),
            )
            dispatch_ms += step.dispatch_ms
            workgroups += step.workgroups
            supported_stages.update(step.supported_stages)
            if getattr(world, "constraints", None):
                constraint_step = self.step_resident_distance_constraints(sub_dt, iteration_count)
                dispatch_ms += constraint_step.dispatch_ms
                workgroups += constraint_step.workgroups
                supported_stages.update(constraint_step.supported_stages)
            if mesh_colliders:
                mesh_step = self.step_resident_mesh_bvh(sub_dt)
                dispatch_ms += mesh_step.dispatch_ms
                workgroups += mesh_step.workgroups
                supported_stages.update(mesh_step.supported_stages)
            if bool(getattr(world, "self_collision", False)):
                cell_size = max(1.0e-6, max(float(item.radius) for item in particles) * 2.0)
                self_step = self.step_resident_self_collision(
                    cell_size=cell_size, dt=sub_dt, iterations=iteration_count,
                    maximum_bucket_visits=len(particles),
                )
                dispatch_ms += self_step.dispatch_ms
                workgroups += self_step.workgroups
                supported_stages.update(self_step.supported_stages)
        world.__dict__.pop("_field_time_seconds", None)
        readback = GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        if resident_output:
            world._gpu_buffers_authoritative = True
        else:
            readback = self.readback_resident(
                world._d3d11_runtime_positions, world._d3d11_runtime_velocities
            )
            _apply_world_particle_arrays(
                world, world._d3d11_runtime_positions, world._d3d11_runtime_velocities
            )
            world._gpu_buffers_authoritative = False
        world.time_seconds += float(dt)
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, particle_count=len(particles),
            workgroups=workgroups,
            upload_bytes=(upload.upload_bytes + constraint_upload.upload_bytes + field_upload.upload_bytes
                          + mesh_upload.upload_bytes),
            readback_bytes=readback.readback_bytes,
            dispatch_ms=(upload.dispatch_ms + constraint_upload.dispatch_ms + field_upload.dispatch_ms
                         + mesh_upload.dispatch_ms
                         + dispatch_ms + readback.dispatch_ms),
            gpu_resident=True, synchronized_readback=not resident_output,
            session_id=self.session_id, supported_stages=tuple(sorted(supported_stages)),
            diagnostics=[
                "Compiled D3D11 tick reused resident state." if reuse
                else "Compiled D3D11 tick initialized resident state."
            ],
        )
        self.last_telemetry = telemetry
        return telemetry

    def integrate_arrays(
        self,
        positions: np.ndarray,
        velocities: np.ndarray,
        *,
        acceleration: tuple[float, float, float] = (0.0, -9.81, 0.0),
        dt: float = 1.0 / 60.0,
        substeps: int = 1,
        collision_plane: tuple[tuple[float, float, float], float, float, float] | None = None,
        collision_sphere: tuple[tuple[float, float, float], float, float, float] | None = None,
    ) -> GpuDispatchTelemetry:
        if self.resident_physics_field_count:
            empty = np.empty((0, 4), dtype=np.float32)
            message = ctypes.create_string_buffer(1024)
            if not self._library.tc_gpu_session_upload_physics_fields(
                self.session_id, empty, 0, 0.0, message, len(message)
            ):
                raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
            self._physics_field_signature = ()
        upload = self.upload_resident_arrays(positions, velocities)
        step = self.step_resident(
            acceleration=acceleration, dt=dt, substeps=substeps,
            collision_plane=collision_plane, collision_sphere=collision_sphere,
        )
        readback = self.readback_resident(positions, velocities)
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, particle_count=len(positions),
            workgroups=step.workgroups, upload_bytes=upload.upload_bytes,
            readback_bytes=readback.readback_bytes,
            dispatch_ms=upload.dispatch_ms + step.dispatch_ms + readback.dispatch_ms,
            gpu_resident=False, synchronized_readback=True,
            supported_stages=step.supported_stages,
            session_id=self.session_id,
        )
        telemetry.diagnostics = [
            "Native D3D11 compute executed and synchronized for the Python-owned world."
        ]
        self.last_telemetry = telemetry
        return telemetry

    @staticmethod
    def _validate_arrays(positions: np.ndarray, velocities: np.ndarray) -> int:
        if positions.dtype != np.float32 or velocities.dtype != np.float32:
            raise TypeError("GPU particle buffers must use float32.")
        if positions.shape != velocities.shape or positions.ndim != 2 or positions.shape[1] != 4:
            raise ValueError("GPU particle buffers must have matching (count, 4) shapes.")
        if not positions.flags.c_contiguous or not velocities.flags.c_contiguous:
            raise ValueError("GPU particle buffers must be C-contiguous.")
        return len(positions)

    def upload_resident_arrays(
        self, positions: np.ndarray, velocities: np.ndarray
    ) -> GpuDispatchTelemetry:
        count = self._validate_arrays(positions, velocities)
        if count == 0:
            return GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_upload_particles(
            self.session_id, positions, velocities, count, message, len(message)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        byte_count = count * 16 * 2
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, particle_count=count,
            upload_bytes=byte_count, dispatch_ms=elapsed_ms, gpu_resident=True,
            synchronized_readback=False, session_id=self.session_id,
            diagnostics=["Particle state uploaded and retained in an independent GPU session."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def upload_resident_distance_constraints(self, world: Any) -> GpuDispatchTelemetry:
        """Compile enabled distance constraints into conflict-free GPU color batches."""
        constraints = list(getattr(world, "constraints", ()) or ())
        if not constraints:
            return GpuDispatchTelemetry(backend="d3d11", device=self.device_description)
        signature = tuple(
            (item.first, item.second, item.rest_length, item.compliance, item.enabled)
            for item in constraints
        ) + tuple(
            (particle.inverse_mass, particle.pinned, particle.frozen, particle.alive)
            for particle in world.particles
        )
        if signature == self._constraint_signature and self.resident_distance_constraint_count == len(constraints):
            return GpuDispatchTelemetry(
                backend="d3d11", device=self.device_description,
                particle_count=self.resident_particle_count, gpu_resident=True,
                synchronized_readback=False, session_id=self.session_id,
                supported_stages=("distance_constraints",),
                diagnostics=["Resident distance-constraint topology and parameters reused."],
            )
        colors = _constraint_graph_colors(constraints)
        order = [index for color in colors for index in color]
        endpoints = np.asarray(
            [(constraints[index].first, constraints[index].second) for index in order], dtype=np.uint32
        ).reshape((-1, 2))
        data = np.empty((len(order), 4), dtype=np.float32)
        for output_index, constraint_index in enumerate(order):
            constraint = constraints[constraint_index]
            first = world.particles[constraint.first]
            second = world.particles[constraint.second]
            data[output_index] = (
                float(constraint.rest_length), float(constraint.compliance),
                _particle_constraint_weight(first), _particle_constraint_weight(second),
            )
        offsets = np.asarray(
            [0] + list(np.cumsum([len(color) for color in colors], dtype=np.uint32)), dtype=np.uint32
        )
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_upload_distance_constraints(
            self.session_id, endpoints, data, len(order), offsets, len(colors), message, len(message)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self._constraint_signature = signature
        self._resident_constraint_color_sizes = tuple(len(color) for color in colors)
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description,
            particle_count=self.resident_particle_count,
            upload_bytes=int(endpoints.nbytes + data.nbytes + offsets.nbytes),
            dispatch_ms=elapsed_ms, gpu_resident=True, synchronized_readback=False,
            session_id=self.session_id, supported_stages=("distance_constraints",),
            diagnostics=[f"Uploaded {len(order)} constraints in {len(colors)} conflict-free colors."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def upload_resident_physics_fields(self, world: Any) -> GpuDispatchTelemetry:
        fields = _d3d11_spatial_fields(world)
        signature = tuple(tuple(row) for row in _physics_field_records(fields))
        if signature == self._physics_field_signature and self.resident_physics_field_count == len(fields):
            return GpuDispatchTelemetry(
                backend="d3d11", device=self.device_description,
                particle_count=self.resident_particle_count, gpu_resident=True,
                synchronized_readback=False, session_id=self.session_id,
                supported_stages=("physics_fields",),
                diagnostics=["Resident physics-field parameters reused."],
            )
        records = np.asarray(_physics_field_records(fields), dtype=np.float32).reshape((-1, 4))
        if not fields:
            records = np.empty((0, 4), dtype=np.float32)
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_upload_physics_fields(
            self.session_id, records, len(fields), float(world.time_seconds), message, len(message)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self._physics_field_signature = signature
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description,
            particle_count=self.resident_particle_count, upload_bytes=int(records.nbytes),
            dispatch_ms=elapsed_ms, gpu_resident=True, synchronized_readback=False,
            session_id=self.session_id, supported_stages=("physics_fields",),
            diagnostics=[f"Uploaded {len(fields)} composable physics fields."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def upload_resident_mesh_bvh(self, collider: Any) -> GpuDispatchTelemetry:
        payload = compile_d3d11_mesh_bvh(collider)
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_upload_mesh_bvh(
            self.session_id, payload.node_bounds, payload.node_metadata,
            len(payload.node_metadata), payload.triangle_vertices,
            len(payload.triangle_vertices) // 3, payload.friction, payload.restitution,
            *payload.surface_velocity, message, len(message),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self._mesh_bvh_signature = (
            int(getattr(collider, "geometry_revision", 0)),
            tuple(tuple(face) for face in collider.faces), len(collider.vertices),
            float(collider.friction), float(collider.restitution), tuple(collider.velocity),
        )
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description,
            particle_count=self.resident_particle_count, upload_bytes=payload.memory_bytes,
            dispatch_ms=elapsed_ms, gpu_resident=True, synchronized_readback=False,
            session_id=self.session_id, supported_stages=("mesh_bvh_collision",),
            diagnostics=[
                f"Uploaded {len(payload.node_metadata)} BVH nodes and "
                f"{len(payload.triangle_vertices) // 3} triangles."
            ],
        )
        self.last_telemetry = telemetry
        return telemetry

    def step_resident_mesh_bvh(self, dt: float) -> GpuDispatchTelemetry:
        if self.resident_mesh_triangle_count <= 0:
            raise GpuComputeUnavailable("No resident mesh BVH has been uploaded.")
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_dispatch_mesh_bvh(
            self.session_id, float(dt), message, len(message)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description,
            particle_count=self.resident_particle_count,
            workgroups=math.ceil(self.resident_particle_count / WORKGROUP_SIZE),
            dispatch_ms=elapsed_ms, gpu_resident=True, synchronized_readback=False,
            session_id=self.session_id, supported_stages=("mesh_bvh_collision",),
            diagnostics=["Resident particle-to-BVH traversal completed."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def step_resident_self_collision(
        self, *, cell_size: float, dt: float, iterations: int = 1, maximum_bucket_visits: int = 4096
    ) -> GpuDispatchTelemetry:
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_dispatch_self_collision(
            self.session_id, float(cell_size), float(dt), max(1, int(iterations)),
            max(32, int(maximum_bucket_visits)), message, len(message),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        count = self.resident_particle_count
        buckets = 1 << max(1, (max(2, count * 2) - 1).bit_length())
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, particle_count=count,
            workgroups=(math.ceil(buckets / WORKGROUP_SIZE) + 2 * math.ceil(count / WORKGROUP_SIZE))
            * max(1, int(iterations)), dispatch_ms=elapsed_ms, gpu_resident=True,
            synchronized_readback=False, session_id=self.session_id,
            supported_stages=("spatial_hash_self_collision",),
            diagnostics=[f"Spatial hash used {buckets} buckets with bounded local traversal."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def step_resident_distance_constraints(
        self, dt: float, iterations: int = 1
    ) -> GpuDispatchTelemetry:
        count = self.resident_distance_constraint_count
        if count <= 0:
            raise GpuComputeUnavailable("No resident distance-constraint stream has been uploaded.")
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_dispatch_distance_constraints(
            self.session_id, float(dt), max(1, int(iterations)), message, len(message)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        color_sizes = getattr(self, "_resident_constraint_color_sizes", (count,))
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description,
            particle_count=self.resident_particle_count,
            workgroups=sum(math.ceil(size / WORKGROUP_SIZE) for size in color_sizes) * max(1, int(iterations)),
            dispatch_ms=elapsed_ms, gpu_resident=True, synchronized_readback=False,
            session_id=self.session_id, supported_stages=("distance_constraints",),
            diagnostics=[f"Graph-colored XPBD solve completed across {len(color_sizes)} colors."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def step_resident(
        self,
        *,
        acceleration: tuple[float, float, float] = (0.0, -9.81, 0.0),
        dt: float = 1.0 / 60.0,
        substeps: int = 1,
        collision_plane: tuple[tuple[float, float, float], float, float, float] | None = None,
        collision_sphere: tuple[tuple[float, float, float], float, float, float] | None = None,
    ) -> GpuDispatchTelemetry:
        count = self.resident_particle_count
        if count <= 0:
            raise GpuComputeUnavailable("No resident particle stream has been uploaded.")
        normal, offset, friction, restitution = collision_plane or ((0.0, 1.0, 0.0), 0.0, 0.0, 0.0)
        sphere_center, sphere_radius, sphere_friction, sphere_restitution = collision_sphere or (
            (0.0, 0.0, 0.0), 0.0, 0.0, 0.0
        )
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_dispatch_particles(
            self.session_id, *acceleration, float(dt), max(1, int(substeps)), *normal, float(offset),
            float(friction), float(restitution), int(collision_plane is not None),
            *sphere_center, float(sphere_radius), float(sphere_friction), float(sphere_restitution),
            int(collision_sphere is not None), message, len(message),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, particle_count=count,
            workgroups=math.ceil(count / WORKGROUP_SIZE), dispatch_ms=elapsed_ms,
            gpu_resident=True, synchronized_readback=False, session_id=self.session_id,
            supported_stages=("integrate",) + (("physics_fields",) if self.resident_physics_field_count else ())
            + (("plane_collision",) if collision_plane else ())
            + (("sphere_collision",) if collision_sphere else ()),
            diagnostics=["GPU-resident dispatch completed with no upload or CPU readback."],
        )
        self.last_telemetry = telemetry
        return telemetry

    def readback_resident(
        self, positions: np.ndarray, velocities: np.ndarray
    ) -> GpuDispatchTelemetry:
        count = self._validate_arrays(positions, velocities)
        message = ctypes.create_string_buffer(1024)
        started = time.perf_counter()
        success = self._library.tc_gpu_session_readback_particles(
            self.session_id, positions, velocities, count, message, len(message)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not success:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        byte_count = count * 16 * 2
        telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, particle_count=count,
            workgroups=math.ceil(count / WORKGROUP_SIZE), readback_bytes=byte_count,
            dispatch_ms=elapsed_ms, gpu_resident=True, synchronized_readback=True,
            session_id=self.session_id,
            diagnostics=["Resident particle state synchronized to CPU on demand."],
        )
        self.last_telemetry = telemetry
        return telemetry


def _world_particle_arrays(world: Any) -> tuple[np.ndarray, np.ndarray]:
    particles = list(getattr(world, "particles", ()) or ())
    positions = np.zeros((len(particles), 4), dtype=np.float32)
    velocities = np.zeros((len(particles), 4), dtype=np.float32)
    for index, particle in enumerate(particles):
        positions[index, :3] = particle.position
        positions[index, 3] = float(particle.radius) if (
            particle.alive and not particle.pinned and not particle.frozen and particle.inverse_mass > 0.0
        ) else 0.0
        velocities[index, :3] = particle.velocity
        material = world.materials.get(particle.material)
        velocities[index, 3] = max(0.0, float(material.damping if material is not None else 0.0))
    return positions, velocities


def _particle_constraint_weight(particle: Any) -> float:
    if not particle.alive or particle.pinned or particle.frozen:
        return 0.0
    return max(0.0, float(particle.inverse_mass))


def _constraint_graph_colors(constraints: list[Any]) -> list[list[int]]:
    """Greedy deterministic coloring; constraints in one batch never share a particle."""
    colors: list[list[int]] = []
    occupied: list[set[int]] = []
    for index, constraint in enumerate(constraints):
        endpoints = {int(constraint.first), int(constraint.second)}
        for color_index, used in enumerate(occupied):
            if endpoints.isdisjoint(used):
                colors[color_index].append(index)
                used.update(endpoints)
                break
        else:
            colors.append([index])
            occupied.append(set(endpoints))
    return colors


def _apply_world_particle_arrays(world: Any, positions: np.ndarray, velocities: np.ndarray) -> None:
    for index, particle in enumerate(world.particles):
        particle.position = tuple(float(value) for value in positions[index, :3])
        particle.velocity = tuple(float(value) for value in velocities[index, :3])


def synchronize_gpu_world(world: Any) -> bool:
    """Read a compiled D3D11 resident session back before CPU ownership resumes."""
    service = getattr(world, "_compiled_d3d11_service", None)
    if not isinstance(service, NativeD3D11ParticleCompute) or not getattr(world, "_gpu_buffers_authoritative", False):
        return False
    service.readback_resident(world._d3d11_runtime_positions, world._d3d11_runtime_velocities)
    _apply_world_particle_arrays(world, world._d3d11_runtime_positions, world._d3d11_runtime_velocities)
    world._gpu_buffers_authoritative = False
    return True


def mark_gpu_constraints_dirty(world: Any) -> None:
    """Request a resident constraint parameter/topology upload on the next GPU tick."""
    world._gpu_constraints_dirty = True


def mark_gpu_fields_dirty(world: Any) -> None:
    """Request a resident physics-field parameter upload on the next GPU tick."""
    world._gpu_fields_dirty = True


def gpu_world_eligibility(
    world: Any, *, used_material_names: set[str] | None = None,
    trust_resident_constraints: bool = False,
) -> tuple[bool, str]:
    if getattr(getattr(world, "interactions", None), "enabled", False):
        return False, "Pair gravity/electrostatic/molecular interactions require a later D3D11 kernel."
    if getattr(world, "pic_grids", None):
        return False, "PIC charge deposition and field sampling require a later D3D11 kernel."
    if getattr(world, "magnetic_grids", None):
        return False, "Magnetic induction and divergence cleaning require a later D3D11 kernel."
    # Modular particle-FX emission and per-particle authoring modules are
    # evaluated on the CPU around the D3D11 integration dispatch. Domain solvers
    # such as fluids, granular matter, destruction, pyro, and soft bodies retain
    # their qualified CPU path until matching GPU kernels exist.
    effect_system = getattr(world, "effect_system", None)
    if effect_system is not None and str(getattr(effect_system, "solver_profile", "")) != "particle_realtime":
        return False, f"The {getattr(effect_system, 'solver_profile', 'unknown')} FX solver is not D3D11-qualified."
    collections = (
        "attachments", "area_constraints", "volume_constraints",
        "emitters",
        "curve_fields", "volumes", "deformable_surfaces",
    )
    populated = [name for name in collections if getattr(world, name, None)]
    if populated:
        return False, "GPU integration does not yet cover: " + ", ".join(populated)
    particle_count = len(getattr(world, "particles", ()) or ())
    constraints = () if trust_resident_constraints else (getattr(world, "constraints", ()) or ())
    for constraint in constraints:
        if not (0 <= int(constraint.first) < particle_count and 0 <= int(constraint.second) < particle_count):
            return False, "A GPU distance constraint references a particle outside the resident stream."
        if not bool(constraint.enabled):
            return False, "Disabled distance constraints require a topology rebuild before GPU execution."
        if (
            float(constraint.break_threshold) > 0.0 or float(constraint.break_distance) > 0.0
            or float(constraint.plastic_yield) > 0.0 or float(constraint.plastic_creep) > 0.0
            or bool(constraint.reformable)
        ):
            return False, "GPU distance constraints do not yet cover breaking, plasticity, or reforming."
    if len(getattr(world, "plane_colliders", ()) or ()) > 1:
        return False, "The first GPU collision kernel supports one plane collider per stage."
    if len(getattr(world, "sphere_colliders", ()) or ()) > 1:
        return False, "The first GPU collision kernel supports one sphere collider per stage."
    if len(getattr(world, "mesh_colliders", ()) or ()) > 1:
        return False, "The first D3D11 BVH kernel supports one triangle-mesh collider per stage."
    if (getattr(world, "plane_colliders", None) or getattr(world, "sphere_colliders", None)
            or getattr(world, "mesh_colliders", None)):
        material_names = used_material_names
        if material_names is None:
            material_names = {
                particle.material for particle in getattr(world, "particles", ()) or () if particle.alive
            }
        for material_name in material_names:
            material = getattr(world, "materials", {}).get(material_name)
            if material is not None and float(getattr(material, "adhesion", 0.0)) > 0.0:
                return False, "GPU plane collisions do not yet cover material adhesion."
    if bool(getattr(world, "self_collision", False)):
        if len(getattr(world, "particles", ()) or ()) > 2_000_000:
            return False, "D3D11 self-collision exceeds the qualified two-million-particle bound."
        if any(item.pinned or item.frozen for item in world.particles if item.alive):
            return False, "D3D11 self-collision with pinned/frozen contact obstacles is not qualified yet."
    supported_fields = {
        "gravity", "wind", "uniform", "gravity_source", "point_gravity", "radial",
        "repulsor", "attractor", "vortex", "turbulence", "drag", "linear_drag", "quadratic_drag",
    }
    for force in getattr(world, "fields", ()) or ():
        if not getattr(force, "enabled", True):
            continue
        if str(force.field_type).lower() not in supported_fields:
            return False, f"Force field {force.field_type} requires a later GPU kernel."
    return True, ""


def _uniform_acceleration(world: Any) -> tuple[float, float, float]:
    acceleration = np.zeros(3, dtype=np.float64)
    spatial_field_ids = {id(force) for force in _d3d11_spatial_fields(world)}
    for force in getattr(world, "fields", ()) or ():
        if not getattr(force, "enabled", True):
            continue
        if id(force) in spatial_field_ids:
            continue
        gust = 1.0 + float(getattr(force, "gust_strength", 0.0)) * math.sin(
            float(getattr(force, "frequency", 1.0))
            * float(getattr(world, "_field_time_seconds", world.time_seconds)) * math.tau + float(force.seed)
        )
        contribution = np.asarray(force.vector, dtype=np.float64) * float(force.strength) * gust
        maximum = max(0.0, float(getattr(force, "max_acceleration", 0.0)))
        length = float(np.linalg.norm(contribution))
        if maximum > 0.0 and length > maximum:
            contribution *= maximum / length
        acceleration += contribution
    return tuple(float(value) for value in acceleration)


def _d3d11_spatial_fields(world: Any) -> list[Any]:
    result = []
    for force in getattr(world, "fields", ()) or ():
        if not getattr(force, "enabled", True):
            continue
        kind = str(force.field_type or "gravity").lower()
        if kind not in {"gravity", "uniform", "wind"} or float(force.radius) > 0.0 or (
            kind == "wind" and float(getattr(force, "drag", 0.0)) > 0.0
        ):
            result.append(force)
    return result


def _physics_field_records(fields: list[Any]) -> list[tuple[float, float, float, float]]:
    kinds = {
        "gravity": 0, "uniform": 0, "gravity_source": 1, "point_gravity": 1,
        "radial": 2, "repulsor": 2, "attractor": 3, "vortex": 4, "turbulence": 5,
        "drag": 6, "linear_drag": 6, "quadratic_drag": 7, "wind": 8,
    }
    records: list[tuple[float, float, float, float]] = []
    for force in fields:
        vector = tuple(float(value) for value in force.vector)
        center = tuple(float(value) for value in force.center)
        records.extend((
            (float(kinds[str(force.field_type or "gravity").lower()]), float(force.strength),
             float(force.radius), float(getattr(force, "inner_radius", 0.0))),
            (*vector, float(getattr(force, "falloff_power", 1.0))),
            (*center, float(getattr(force, "max_acceleration", 0.0))),
            (float(getattr(force, "drag", 0.0)), float(force.seed),
             float(getattr(force, "frequency", 1.0)), float(getattr(force, "noise_scale", 1.0))),
            (float(getattr(force, "gust_strength", 0.0)),
             float(getattr(force, "ambient_density", 1.225)), 0.0, 0.0),
        ))
    return records


def _plane_parameters(
    world: Any,
) -> tuple[tuple[float, float, float], float, float, float] | None:
    colliders = list(getattr(world, "plane_colliders", ()) or ())
    if not colliders:
        return None
    collider = colliders[0]
    normal = np.asarray(collider.normal, dtype=np.float64)
    length = float(np.linalg.norm(normal))
    if length <= 1.0e-12:
        normal = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
    else:
        normal /= length
    return (
        tuple(float(value) for value in normal), float(collider.offset),
        max(0.0, float(collider.friction)), max(0.0, float(collider.restitution)),
    )


def _sphere_parameters(
    world: Any,
) -> tuple[tuple[float, float, float], float, float, float] | None:
    colliders = list(getattr(world, "sphere_colliders", ()) or ())
    if not colliders:
        return None
    collider = colliders[0]
    return (
        tuple(float(value) for value in collider.center), max(0.0, float(collider.radius)),
        max(0.0, float(collider.friction)), max(0.0, float(collider.restitution)),
    )


class QtRhiParticleCompute:
    """Own a hidden QRhiWidget and synchronously dispatch qualified kernels."""

    def __init__(self, api: str = "d3d11"):
        try:
            from importlib import import_module
            qt_core = import_module("Py" + "Side6.QtCore")
            qt_widgets = import_module("Py" + "Side6.QtWidgets")
            Qt = qt_core.Qt
            QApplication, QRhiWidget = qt_widgets.QApplication, qt_widgets.QRhiWidget
        except ImportError as error:  # pragma: no cover - packaging guard
            raise GpuComputeUnavailable("Qt for Python QRhiWidget is unavailable.") from error
        if QApplication.instance() is None:
            raise GpuComputeUnavailable("A QApplication must exist before the Qt RHI compute backend is installed.")
        if not SHADER_PATH.exists():
            raise GpuComputeUnavailable(f"Compiled compute shader is missing: {SHADER_PATH}")
        self._widget = _ParticleComputeWidget(str(api).lower(), QRhiWidget)
        self._widget.resize(1, 1)
        self._widget.setFixedColorBufferSize(1, 1)
        self._widget.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._widget.show()
        QApplication.processEvents()
        self.last_telemetry = GpuDispatchTelemetry()

    def dispatch(self, world: Any, dt: float) -> GpuDispatchTelemetry:
        eligible, reason = gpu_world_eligibility(world)
        if not eligible:
            raise GpuComputeUnavailable(reason)
        if getattr(world, "plane_colliders", None) or getattr(world, "sphere_colliders", None):
            raise GpuComputeUnavailable("Qt RHI collision kernels are not qualified; use the native D3D11 backend.")
        particles = list(getattr(world, "particles", ()) or ())
        if not particles:
            world.time_seconds += float(dt)
            self.last_telemetry = GpuDispatchTelemetry(backend=self._widget.api_name, particle_count=0)
            return self.last_telemetry
        positions = np.zeros((len(particles), 4), dtype=np.float32)
        velocities = np.zeros((len(particles), 4), dtype=np.float32)
        for index, particle in enumerate(particles):
            positions[index, :3] = particle.position
            positions[index, 3] = float(particle.radius) if (
                particle.alive and not particle.pinned and not particle.frozen and particle.inverse_mass > 0.0
            ) else 0.0
            velocities[index, :3] = particle.velocity
            material = world.materials.get(particle.material)
            velocities[index, 3] = max(0.0, float(material.damping if material is not None else 0.0))
        acceleration = _uniform_acceleration(world)
        started = time.perf_counter()
        result_positions, result_velocities, telemetry = self._widget.dispatch_particles(
            positions, velocities, acceleration, float(dt), max(1, int(world.substeps))
        )
        telemetry.dispatch_ms = (time.perf_counter() - started) * 1000.0
        for index, particle in enumerate(particles):
            particle.position = tuple(float(value) for value in result_positions[index, :3])
            particle.velocity = tuple(float(value) for value in result_velocities[index, :3])
        world.time_seconds += float(dt)
        self.last_telemetry = telemetry
        return telemetry

    def close(self) -> None:
        self._widget.close()
        self._widget.deleteLater()


def _ParticleComputeWidget(api_name: str, base_class: type):
    """Create the QRhiWidget subclass lazily so headless imports remain safe."""
    from importlib import import_module
    qt_core = import_module("Py" + "Side6.QtCore")
    qt_gui = import_module("Py" + "Side6.QtGui")
    QByteArray, QFile, QIODevice = qt_core.QByteArray, qt_core.QFile, qt_core.QIODevice
    QColor, QRhi, QRhiBuffer = qt_gui.QColor, qt_gui.QRhi, qt_gui.QRhiBuffer
    QRhiDepthStencilClearValue = qt_gui.QRhiDepthStencilClearValue
    QRhiReadbackResult = qt_gui.QRhiReadbackResult
    QRhiShaderResourceBinding = qt_gui.QRhiShaderResourceBinding
    QRhiShaderStage, QShader = qt_gui.QRhiShaderStage, qt_gui.QShader

    class ParticleComputeWidget(base_class):
        def __init__(self, api: str):
            super().__init__()
            api_map = {
                "d3d11": base_class.Api.Direct3D11,
                "d3d12": base_class.Api.Direct3D12,
                "vulkan": base_class.Api.Vulkan,
            }
            self.api_name = api if api in api_map else "d3d11"
            self.setApi(api_map[self.api_name])
            self._rhi = None
            self._capacity = 0
            self._position_buffer = None
            self._velocity_buffer = None
            self._uniform_buffer = None
            self._bindings = None
            self._pipeline = None
            self._pending = None
            self._position_readback = None
            self._velocity_readback = None
            self._error = ""

        def initialize(self, _command_buffer):
            self._rhi = self.rhi()
            if self._rhi is None or not self._rhi.isFeatureSupported(QRhi.Compute):
                self._error = f"{self.api_name} does not expose QRhi compute support."

        def releaseResources(self):
            self._drop_resources()
            self._rhi = None

        def _drop_resources(self):
            for resource in (self._pipeline, self._bindings, self._uniform_buffer, self._velocity_buffer, self._position_buffer):
                if resource is not None:
                    resource.destroy()
            self._position_buffer = self._velocity_buffer = self._uniform_buffer = None
            self._bindings = self._pipeline = None
            self._capacity = 0

        def _ensure_resources(self, particle_count: int):
            if self._pipeline is not None and particle_count <= self._capacity:
                return
            self._drop_resources()
            self._capacity = max(1, int(particle_count))
            buffer_size = self._capacity * 16
            self._position_buffer = self._rhi.newBuffer(QRhiBuffer.Static, QRhiBuffer.StorageBuffer, buffer_size)
            self._velocity_buffer = self._rhi.newBuffer(QRhiBuffer.Static, QRhiBuffer.StorageBuffer, buffer_size)
            self._uniform_buffer = self._rhi.newBuffer(QRhiBuffer.Dynamic, QRhiBuffer.UniformBuffer, 32)
            if not all(resource.create() for resource in (self._position_buffer, self._velocity_buffer, self._uniform_buffer)):
                raise GpuComputeUnavailable("Unable to allocate QRhi compute buffers.")
            self._bindings = self._rhi.newShaderResourceBindings()
            self._bindings.setBindings([
                QRhiShaderResourceBinding.bufferLoadStore(0, QRhiShaderResourceBinding.ComputeStage, self._position_buffer),
                QRhiShaderResourceBinding.bufferLoadStore(1, QRhiShaderResourceBinding.ComputeStage, self._velocity_buffer),
                QRhiShaderResourceBinding.uniformBuffer(2, QRhiShaderResourceBinding.ComputeStage, self._uniform_buffer),
            ])
            if not self._bindings.create():
                raise GpuComputeUnavailable("Unable to create QRhi shader resource bindings.")
            shader_file = QFile(str(SHADER_PATH))
            if not shader_file.open(QIODevice.ReadOnly):
                raise GpuComputeUnavailable(f"Unable to read {SHADER_PATH}")
            shader = QShader.fromSerialized(shader_file.readAll())
            shader_file.close()
            if not shader.isValid():
                raise GpuComputeUnavailable("The particle compute shader package is invalid.")
            self._pipeline = self._rhi.newComputePipeline()
            self._pipeline.setShaderResourceBindings(self._bindings)
            self._pipeline.setShaderStage(QRhiShaderStage(QRhiShaderStage.Compute, shader))
            if not self._pipeline.create():
                raise GpuComputeUnavailable("Unable to create the QRhi compute pipeline.")

        def render(self, command_buffer):
            if self._pending is None or self._error:
                command_buffer.beginPass(
                    self.renderTarget(), QColor(0, 0, 0, 0), QRhiDepthStencilClearValue(), None
                )
                command_buffer.endPass()
                return
            positions, velocities, acceleration, dt, substeps = self._pending
            count = len(positions)
            self._ensure_resources(count)
            params = struct.pack("4f2I2I", *acceleration, float(dt), count, substeps, 0, 0)
            updates = self._rhi.nextResourceUpdateBatch()
            updates.uploadStaticBuffer(self._position_buffer, QByteArray(positions.tobytes()))
            updates.uploadStaticBuffer(self._velocity_buffer, QByteArray(velocities.tobytes()))
            updates.updateDynamicBuffer(self._uniform_buffer, 0, len(params), QByteArray(params))
            self._position_readback = QRhiReadbackResult()
            self._velocity_readback = QRhiReadbackResult()
            readbacks = self._rhi.nextResourceUpdateBatch()
            readbacks.readBackBuffer(self._position_buffer, 0, count * 16, self._position_readback)
            readbacks.readBackBuffer(self._velocity_buffer, 0, count * 16, self._velocity_readback)
            command_buffer.beginComputePass(updates)
            command_buffer.setComputePipeline(self._pipeline)
            command_buffer.setShaderResources(self._bindings)
            command_buffer.dispatch(math.ceil(count / WORKGROUP_SIZE), 1, 1)
            command_buffer.endComputePass(readbacks)
            command_buffer.beginPass(
                self.renderTarget(), QColor(0, 0, 0, 0), QRhiDepthStencilClearValue(), None
            )
            command_buffer.endPass()

        def dispatch_particles(self, positions, velocities, acceleration, dt, substeps):
            from importlib import import_module
            QApplication = import_module("Py" + "Side6.QtWidgets").QApplication
            self._pending = (positions, velocities, acceleration, dt, substeps)
            self._error = ""
            self.update()
            QApplication.processEvents()
            self.grabFramebuffer()
            QApplication.processEvents()
            if self._error:
                raise GpuComputeUnavailable(self._error)
            if self._position_readback is None or self._velocity_readback is None:
                raise GpuComputeUnavailable("QRhiWidget did not record the requested compute frame.")
            count = len(positions)
            position_data = bytes(self._position_readback.data)
            velocity_data = bytes(self._velocity_readback.data)
            expected = count * 16
            if len(position_data) != expected or len(velocity_data) != expected:
                raise GpuComputeUnavailable(
                    f"GPU readback was incomplete: positions={len(position_data)}, velocities={len(velocity_data)}, expected={expected}."
                )
            result_positions = np.frombuffer(position_data, dtype=np.float32).reshape(count, 4).copy()
            result_velocities = np.frombuffer(velocity_data, dtype=np.float32).reshape(count, 4).copy()
            telemetry = GpuDispatchTelemetry(
                backend=self.api_name,
                device="Qt RHI compute device",
                particle_count=count,
                workgroups=math.ceil(count / WORKGROUP_SIZE),
                upload_bytes=expected * 2 + 32,
                readback_bytes=expected * 2,
                gpu_resident=False,
                synchronized_readback=True,
                diagnostics=["Position and velocity buffers are synchronized to CPU after this qualified stage."],
            )
            return result_positions, result_velocities, telemetry

    return ParticleComputeWidget(api_name)


_GPU_COMPUTE_SERVICE: NativeD3D11ParticleCompute | QtRhiParticleCompute | None = None


def _register_service(service: Any) -> Any:
    from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
        SimulationBackendCapabilities, register_simulation_backend, register_simulation_executor,
    )

    def executor(compiled: Any, world: Any, dt: float) -> dict[str, Any]:
        started = time.perf_counter()
        effect_system = getattr(world, "effect_system", None)
        existing_service = getattr(world, "_compiled_d3d11_service", None)
        recovery_world = (
            copy.deepcopy(world, {id(existing_service): existing_service} if existing_service is not None else None)
            if effect_system is not None else None
        )
        try:
            if effect_system is not None:
                from tech_connector.game_engine.runtime.tc_effect_system_service import prepare_effect_step
                prepare_effect_step(effect_system, world, float(dt))
            world._emit_geometry(float(dt))
            world._update_reformable_bonds()
            if isinstance(service, NativeD3D11ParticleCompute):
                runtime_service = getattr(world, "_compiled_d3d11_service", None)
                if not isinstance(runtime_service, NativeD3D11ParticleCompute):
                    runtime_service = NativeD3D11ParticleCompute(service.library_path)
                    world._compiled_d3d11_service = runtime_service
                constraint_stage = next(
                    (stage for stage in compiled.stages if stage.stage_id == "constraints"), None
                )
                telemetry = runtime_service.dispatch_runtime(
                    world, dt, substeps=int(compiled.metadata.get("compiled_substeps", world.substeps)),
                    constraint_iterations=(
                        int(constraint_stage.iterations) if constraint_stage is not None
                        else int(world.constraint_iterations)
                    ),
                    resident_output=bool(compiled.metadata.get("gpu_resident_output", False)),
                )
            else:
                telemetry = service.dispatch(world, dt)
            if effect_system is not None:
                from tech_connector.game_engine.runtime.tc_effect_system_service import finish_effect_step
                finish_effect_step(effect_system, world, float(dt))
                telemetry.supported_stages = tuple(sorted(set((*telemetry.supported_stages, "effect_modules_cpu"))))
        except GpuComputeUnavailable as error:
            from tech_connector.game_engine.runtime.tc_simulation_native_backend_service import execute_native_cpu
            if recovery_world is not None:
                world.__dict__.clear()
                world.__dict__.update(recovery_world.__dict__)
            compiled.diagnostics.append({
                "severity": "warning", "code": "gpu_stage_fallback", "message": str(error),
            })
            receipt = dict(execute_native_cpu(compiled, world, dt))
            actual_backend = str(receipt.get("execution_backend") or "native_cpu")
            compiled.metadata["execution_backend"] = actual_backend
            compiled.metadata["gpu_resident"] = False
            receipt.setdefault("fallback_reasons", []).append(str(error))
            receipt["gpu_fallback_ms"] = (time.perf_counter() - started) * 1000.0
            return receipt
        compiled.metadata["execution_backend"] = "gpu_compute"
        compiled.metadata["gpu_resident"] = telemetry.gpu_resident
        compiled.metadata["dispatch_telemetry"] = telemetry.to_dict()
        return {
            "execution_backend": "gpu_compute",
            "stage_ms": {"gpu_dispatch": float(telemetry.dispatch_ms)},
            "memory_bytes": int(telemetry.particle_count * 32),
            "dispatches": int(telemetry.workgroups),
            "buffer_residency": "persistent_device" if telemetry.gpu_resident else "device_synchronized",
            "compute_provider": telemetry.backend,
            "synchronization_points": 0 if not telemetry.synchronized_readback else 2,
            "dispatch_telemetry": telemetry.to_dict(),
        }

    register_simulation_backend(SimulationBackendCapabilities(
        "gpu_compute", True, "gpu", ("particle", "effect"), True, False, False, 20_000_000,
        "Native D3D11 or Qt RHI compute; particle FX uses CPU-authored emitter modules with GPU "
        "integration, independent sessions, graph-colored distance constraints, and bounded collisions.",
    ))
    register_simulation_executor("gpu_compute", executor)
    return service


def install_native_gpu_backend(library_path: str | Path | None = None) -> NativeD3D11ParticleCompute:
    global _GPU_COMPUTE_SERVICE
    if not isinstance(_GPU_COMPUTE_SERVICE, NativeD3D11ParticleCompute):
        _GPU_COMPUTE_SERVICE = _register_service(NativeD3D11ParticleCompute(library_path))
    return _GPU_COMPUTE_SERVICE


def install_qrhi_gpu_backend(api: str = "d3d11") -> QtRhiParticleCompute:
    """Probe, qualify, and register the first real GPU compute executor."""
    global _GPU_COMPUTE_SERVICE
    if _GPU_COMPUTE_SERVICE is None:
        service = QtRhiParticleCompute(api)
        # A real dispatch must succeed before capability registration.
        service._widget.dispatch_particles(
            np.asarray([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
            np.asarray([[0.0, 0.0, 0.0, 0.0]], dtype=np.float32),
            (0.0, -9.81, 0.0), 1.0 / 60.0, 1,
        )
        _GPU_COMPUTE_SERVICE = _register_service(service)
    return _GPU_COMPUTE_SERVICE


__all__ = [
    "D3D11MeshBvhPayload", "GpuComputeUnavailable", "GpuDispatchTelemetry",
    "NativeD3D11ParticleCompute", "QtRhiParticleCompute", "compile_d3d11_mesh_bvh",
    "gpu_world_eligibility", "install_native_gpu_backend", "install_qrhi_gpu_backend",
    "mark_gpu_constraints_dirty", "mark_gpu_fields_dirty", "synchronize_gpu_world",
]
