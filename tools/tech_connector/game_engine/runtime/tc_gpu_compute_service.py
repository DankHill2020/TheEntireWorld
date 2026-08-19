"""Native D3D11 and Qt RHI compute executors for Tech Connector particles.

The native kernel covers uniform-force integration plus one plane and one sphere
collider, with independent upload, resident dispatch, and on-demand readback sessions.
Unsupported worlds fail closed to the reference executor so backend status and
performance telemetry remain honest as coverage grows stage-by-stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
        message = ctypes.create_string_buffer(1024)
        if not self._library.tc_gpu_compute_available(message, len(message)):
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self.device_description = message.value.decode("utf-8", errors="replace")
        message = ctypes.create_string_buffer(1024)
        self.session_id = int(self._library.tc_gpu_session_create(message, len(message)))
        if self.session_id == 0:
            raise GpuComputeUnavailable(message.value.decode("utf-8", errors="replace"))
        self._closed = False
        self.last_telemetry = GpuDispatchTelemetry(
            backend="d3d11", device=self.device_description, session_id=self.session_id
        )

    @property
    def resident_particle_count(self) -> int:
        return 0 if self._closed else int(self._library.tc_gpu_session_particle_count(self.session_id))

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
            supported_stages=("integrate",) + (("plane_collision",) if collision_plane else ())
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


def gpu_world_eligibility(world: Any) -> tuple[bool, str]:
    if getattr(world, "effect_system", None) is not None:
        return False, "Modular effect spawn/update stages are not GPU-qualified yet."
    collections = (
        "constraints", "attachments", "area_constraints", "volume_constraints",
        "mesh_colliders", "emitters",
        "curve_fields", "volumes", "deformable_surfaces",
    )
    populated = [name for name in collections if getattr(world, name, None)]
    if populated:
        return False, "GPU integration does not yet cover: " + ", ".join(populated)
    if len(getattr(world, "plane_colliders", ()) or ()) > 1:
        return False, "The first GPU collision kernel supports one plane collider per stage."
    if len(getattr(world, "sphere_colliders", ()) or ()) > 1:
        return False, "The first GPU collision kernel supports one sphere collider per stage."
    if getattr(world, "plane_colliders", None) or getattr(world, "sphere_colliders", None):
        for particle in getattr(world, "particles", ()) or ():
            material = getattr(world, "materials", {}).get(particle.material)
            if material is not None and float(getattr(material, "adhesion", 0.0)) > 0.0:
                return False, "GPU plane collisions do not yet cover material adhesion."
    if bool(getattr(world, "self_collision", False)):
        return False, "GPU self-collision is not qualified yet."
    for force in getattr(world, "fields", ()) or ():
        if str(force.field_type).lower() not in {"gravity", "wind", "uniform"} or float(force.radius) > 0.0:
            return False, f"Force field {force.field_type} requires a later GPU kernel."
    return True, ""


def _uniform_acceleration(world: Any) -> tuple[float, float, float]:
    acceleration = np.zeros(3, dtype=np.float64)
    for force in getattr(world, "fields", ()) or ():
        acceleration += np.asarray(force.vector, dtype=np.float64) * float(force.strength)
    return tuple(float(value) for value in acceleration)


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
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication, QRhiWidget
        except ImportError as error:  # pragma: no cover - packaging guard
            raise GpuComputeUnavailable("PySide6 QRhiWidget is unavailable.") from error
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
    from PySide6.QtCore import QByteArray, QFile, QIODevice
    from PySide6.QtGui import (
        QColor, QRhi, QRhiBuffer, QRhiDepthStencilClearValue, QRhiReadbackResult,
        QRhiShaderResourceBinding, QRhiShaderStage, QShader,
    )

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
            from PySide6.QtWidgets import QApplication
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

    def executor(compiled: Any, world: Any, dt: float) -> None:
        try:
            telemetry = service.dispatch(world, dt)
        except GpuComputeUnavailable as error:
            from tech_connector.game_engine.runtime.tc_simulation_ir_service import execute_compiled_reference
            compiled.diagnostics.append({
                "severity": "warning", "code": "gpu_stage_fallback", "message": str(error),
            })
            compiled.metadata["execution_backend"] = "reference_cpu"
            compiled.metadata["gpu_resident"] = False
            execute_compiled_reference(compiled, world, dt)
            return
        compiled.metadata["execution_backend"] = "gpu_compute"
        compiled.metadata["gpu_resident"] = telemetry.gpu_resident
        compiled.metadata["dispatch_telemetry"] = telemetry.to_dict()

    register_simulation_backend(SimulationBackendCapabilities(
        "gpu_compute", True, "gpu", ("particle",), True, False, False, 20_000_000,
        "Native D3D11 or Qt RHI compute; native path supports independent sessions plus one plane and sphere collider.",
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
    "GpuComputeUnavailable", "GpuDispatchTelemetry", "NativeD3D11ParticleCompute", "QtRhiParticleCompute",
    "gpu_world_eligibility", "install_native_gpu_backend", "install_qrhi_gpu_backend",
]
