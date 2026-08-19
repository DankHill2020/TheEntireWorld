"""Backend-independent compilation contract for TC simulation and effects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any


@dataclass(frozen=True)
class SimulationExecutionProfile:
    name: str
    target_frame_ms: float
    substep_scale: float
    iteration_scale: float
    particle_scale: float
    volume_resolution_scale: float
    solver_precision: str
    render_style: str
    deterministic: bool = True
    prefer_gpu: bool = True
    allow_topology_changes: bool = True
    stateless_effects: bool = False


EXECUTION_PROFILES = {
    "cinematic": SimulationExecutionProfile("cinematic", 33.3, 2.0, 2.0, 1.75, 1.5, "float64", "photoreal"),
    "photoreal": SimulationExecutionProfile("photoreal", 16.6, 1.5, 1.5, 1.25, 1.25, "float32", "photoreal"),
    "realtime": SimulationExecutionProfile("realtime", 4.0, 1.0, 1.0, 1.0, 1.0, "float32", "photoreal"),
    "mobile": SimulationExecutionProfile("mobile", 2.0, 0.55, 0.5, 0.4, 0.5, "float16", "simplified", allow_topology_changes=False, stateless_effects=True),
    "toony": SimulationExecutionProfile("toony", 4.0, 0.8, 0.8, 0.8, 0.75, "float32", "toony"),
    "stylized": SimulationExecutionProfile("stylized", 4.0, 0.8, 0.8, 0.8, 0.75, "float32", "stylized"),
    "retro": SimulationExecutionProfile("retro", 1.0, 0.35, 0.3, 0.15, 0.25, "float16", "retro", allow_topology_changes=False, stateless_effects=True),
}


@dataclass(frozen=True)
class SimulationBackendCapabilities:
    backend_id: str
    available: bool
    execution_device: str
    domains: tuple[str, ...]
    deterministic: bool
    topology_changes: bool
    sparse_volumes: bool
    max_particles: int
    notes: str = ""


BACKENDS = {
    "reference_cpu": SimulationBackendCapabilities(
        "reference_cpu", True, "cpu",
        ("cloth", "softbody", "fluid", "particle", "volume", "rigid", "effect", "surface"),
        True, True, True, 100_000,
        "Deterministic Python reference backend for correctness tests and fallback playback.",
    ),
    "native_cpu": SimulationBackendCapabilities(
        "native_cpu", False, "cpu",
        ("cloth", "softbody", "fluid", "particle", "volume", "rigid", "effect", "surface"),
        True, True, True, 2_000_000,
        "Planned SIMD/task-graph backend.",
    ),
    "gpu_compute": SimulationBackendCapabilities(
        "gpu_compute", False, "gpu",
        ("cloth", "softbody", "fluid", "particle", "volume", "rigid", "effect", "surface"),
        True, True, True, 20_000_000,
        "Planned compute backend with graph-colored constraints, GPU broadphase, and sparse grids.",
    ),
}

SIMULATION_EXECUTORS: dict[str, Any] = {}


@dataclass
class SimulationResource:
    resource_id: str
    resource_type: str
    element_count: int
    access: str = "read_write"
    format: str = "structured"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationStage:
    stage_id: str
    stage_type: str
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    iterations: int = 1
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledSimulationIR:
    profile: SimulationExecutionProfile
    backend: SimulationBackendCapabilities
    domains: list[str]
    resources: list[SimulationResource]
    stages: list[SimulationStage]
    outputs: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        resource_ids = {item.resource_id for item in self.resources}
        stage_ids: set[str] = set()
        for stage in self.stages:
            if stage.stage_id in stage_ids:
                errors.append(f"Duplicate simulation stage: {stage.stage_id}")
            stage_ids.add(stage.stage_id)
            for resource_id in stage.reads + stage.writes:
                if resource_id not in resource_ids:
                    errors.append(f"{stage.stage_id}: unknown resource {resource_id}")
        unsupported = sorted(set(self.domains) - set(self.backend.domains))
        if unsupported:
            errors.append("Backend does not support domains: " + ", ".join(unsupported))
        # Availability describes whether this process can execute the backend;
        # it does not invalidate a portable IR compiled for that backend.
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.simulation_ir.v1",
            "profile": asdict(self.profile),
            "backend": asdict(self.backend),
            "domains": list(self.domains),
            "resources": [asdict(item) for item in self.resources],
            "stages": [asdict(item) for item in self.stages],
            "outputs": list(self.outputs),
            "diagnostics": list(self.diagnostics),
            "metadata": dict(self.metadata),
        }


def register_simulation_backend(capabilities: SimulationBackendCapabilities) -> None:
    BACKENDS[str(capabilities.backend_id)] = capabilities


def register_simulation_executor(backend_id: str, executor: Any) -> None:
    if not callable(executor):
        raise TypeError("A simulation runtime executor must be callable.")
    SIMULATION_EXECUTORS[str(backend_id)] = executor


def simulation_backend_status(backend_id: str) -> dict[str, Any]:
    """Return the truthful runtime state shown by authoring and diagnostics UI."""
    capabilities = BACKENDS.get(str(backend_id))
    if capabilities is None:
        raise KeyError(f"Unknown simulation backend: {backend_id}")
    executor_installed = callable(SIMULATION_EXECUTORS.get(capabilities.backend_id))
    available = bool(capabilities.available and executor_installed)
    reason = ""
    if not capabilities.available:
        reason = capabilities.notes or "The backend is not installed in this process."
    elif not executor_installed:
        reason = "Backend capabilities are registered, but no runtime executor is installed."
    return {
        "backend_id": capabilities.backend_id,
        "available": available,
        "executor_installed": executor_installed,
        "execution_device": capabilities.execution_device,
        "domains": list(capabilities.domains),
        "deterministic": capabilities.deterministic,
        "topology_changes": capabilities.topology_changes,
        "sparse_volumes": capabilities.sparse_volumes,
        "max_particles": capabilities.max_particles,
        "reason": reason,
    }


def simulation_backend_statuses() -> list[dict[str, Any]]:
    return [simulation_backend_status(backend_id) for backend_id in BACKENDS]


def compile_simulation_world(
    world: Any,
    *,
    profile: str = "realtime",
    backend: str = "auto",
) -> CompiledSimulationIR:
    """Compile a mutable reference world into a validated staged execution plan."""
    execution_profile = EXECUTION_PROFILES.get(str(profile).lower())
    if execution_profile is None:
        raise KeyError(f"Unknown simulation execution profile: {profile}")
    domains = _simulation_domains(world)
    selected_backend, diagnostics = _select_backend(domains, execution_profile, backend)
    particle_count = len(getattr(world, "particles", ()) or ())
    constraint_count = (
        len(getattr(world, "constraints", ()) or ())
        + len(getattr(world, "area_constraints", ()) or ())
        + len(getattr(world, "volume_constraints", ()) or ())
        + len(getattr(world, "attachments", ()) or ())
    )
    collider_count = (
        len(getattr(world, "plane_colliders", ()) or ())
        + len(getattr(world, "sphere_colliders", ()) or ())
        + len(getattr(world, "mesh_colliders", ()) or ())
    )
    resources = [
        SimulationResource("particles", "particle_soa", particle_count, format=execution_profile.solver_precision),
        SimulationResource("constraints", "constraint_soa", constraint_count),
        SimulationResource("colliders", "collision_acceleration", collider_count, access="read"),
        SimulationResource("events", "event_stream", 0, format="append_buffer"),
        SimulationResource("cache_frames", "versioned_frame_cache", 0, format="tc.sim_cache.v2"),
    ]
    effect_system = getattr(world, "effect_system", None)
    data_channels = dict(getattr(effect_system, "data_channels", {}) or {})
    subgraphs = dict(getattr(effect_system, "subgraphs", {}) or {})
    subgraph_errors = [f"{key}: {error}" for key, graph in subgraphs.items() for error in graph.validate()]
    if subgraph_errors:
        raise ValueError("Invalid FX subgraphs: " + "; ".join(subgraph_errors))
    channel_resources: list[str] = []
    for channel_id, channel in sorted(data_channels.items()):
        resource_id = f"data_channel.{channel_id}"
        channel_resources.append(resource_id)
        resources.append(SimulationResource(
            resource_id, "typed_event_stream", 0, format="append_buffer",
            metadata={"capacity": channel.schema.capacity, "scope": channel.schema.scope,
                      "schema": channel.schema.to_dict()},
        ))
    if getattr(world, "volumes", None):
        cell_count = sum(len(volume.cells) for volume in world.volumes.values())
        resources.append(SimulationResource(
            "sparse_volume", "sparse_tiled_grid", cell_count,
            metadata={"resolution_scale": execution_profile.volume_resolution_scale},
        ))
    if set(domains) & {"fluid", "effect", "volume", "rigid"}:
        resources.append(SimulationResource("secondary", "secondary_effect_stream", 0, format="append_buffer"))
    if "fluid" in domains or "surface" in domains:
        resources.append(SimulationResource("surface_mesh", "surface_mesh", 0, format="triangle_mesh"))
    stages = [
        SimulationStage("emit", "source_and_spawn", writes=["particles", "events"]),
        SimulationStage("integrate", "integrate_forces", reads=["particles"], writes=["particles"]),
        SimulationStage("broadphase", "spatial_hash_or_bvh", reads=["particles", "colliders"], writes=["events"]),
        SimulationStage(
            "constraints", "xpbd_constraint_batches", reads=["constraints", "particles"], writes=["particles"],
            iterations=max(1, round(int(getattr(world, "constraint_iterations", 1)) * execution_profile.iteration_scale)),
            parameters={"graph_coloring_required": selected_backend.execution_device == "gpu"},
        ),
        SimulationStage("collision", "continuous_contact", reads=["colliders", "particles"], writes=["particles", "events"]),
    ]
    if getattr(world, "volumes", None):
        stages.append(SimulationStage(
            "volume", "sparse_volume_solve", reads=["sparse_volume", "particles"], writes=["sparse_volume"],
            parameters={"operations": ["advect", "project", "combust", "dissipate"]},
        ))
    if set(domains) & {"fluid", "effect", "volume", "rigid"}:
        stages.append(SimulationStage(
            "secondary", "secondary_effect_generation", reads=["particles", "events"],
            writes=["secondary"], parameters={"outputs": ["foam", "spray", "mist", "debris", "dust"]},
        ))
    if "fluid" in domains or "surface" in domains:
        stages.append(SimulationStage(
            "surface", "particle_or_field_meshing", reads=["particles"], writes=["surface_mesh"],
            parameters={"preview_decimation": True, "production_meshing": True},
        ))
    if getattr(world, "effect_system", None) is not None:
        stateless = effect_system_is_stateless(world.effect_system)
        stages.append(SimulationStage(
            "effects", "stateless_effect" if stateless and execution_profile.stateless_effects else "stateful_effect_graph",
            reads=["particles", "events"], writes=["particles", "events"],
            parameters={"stateless_eligible": stateless, "subgraphs": sorted(subgraphs)},
        ))
    if channel_resources:
        stages.append(SimulationStage(
            "data_channels", "typed_event_routing", reads=["events"], writes=channel_resources,
            parameters={"channels": sorted(data_channels), "bounded": True, "tick_deterministic": True},
        ))
    stages.append(SimulationStage("render_prepare", "render_stream_compaction", reads=["particles"], writes=["events"]))
    stages.append(SimulationStage(
        "cache", "versioned_resumable_cache", reads=["particles", "events"], writes=["cache_frames"],
        enabled=False, parameters={"resume_supported": True, "checkpoint_supported": True},
    ))
    outputs = _compiled_outputs(domains, execution_profile)
    compiled = CompiledSimulationIR(
        execution_profile,
        selected_backend,
        domains,
        resources,
        stages,
        outputs,
        diagnostics,
        {
            "source_substeps": int(getattr(world, "substeps", 1)),
            "compiled_substeps": max(1, round(int(getattr(world, "substeps", 1)) * execution_profile.substep_scale)),
            "target_frame_ms": execution_profile.target_frame_ms,
            "particle_budget": min(selected_backend.max_particles, max(1, round(particle_count * execution_profile.particle_scale))),
            "reference_world_attached": True,
            "requested_backend": str(backend or "auto"),
            "execution_backend": (
                selected_backend.backend_id
                if simulation_backend_status(selected_backend.backend_id)["available"]
                else "reference_cpu"
            ),
            "gpu_resident": bool(
                selected_backend.execution_device == "gpu"
                and simulation_backend_status(selected_backend.backend_id)["available"]
            ),
            "workflow": dict(getattr(getattr(world, "effect_system", None), "workflow", {}) or {}),
        },
    )
    errors = compiled.validate()
    if errors:
        raise ValueError("Invalid compiled simulation IR: " + "; ".join(errors))
    return compiled


def execute_compiled_reference(compiled: CompiledSimulationIR, world: Any, dt: float) -> None:
    """Execute a compatible compiled plan with the deterministic reference solver.

    :param compiled: Validated simulation IR.
    :param world: Mutable reference simulation world.
    :param dt: Tick duration in seconds.
    :return: None.
    """

    substeps = int(getattr(world, "substeps", 1))
    iterations = int(getattr(world, "constraint_iterations", 1))
    try:
        world.substeps = int(compiled.metadata["compiled_substeps"])
        constraint_stage = next(stage for stage in compiled.stages if stage.stage_id == "constraints")
        world.constraint_iterations = int(constraint_stage.iterations)
        world.step(float(dt))
    finally:
        world.substeps = substeps
        world.constraint_iterations = iterations


def execute_compiled_simulation(compiled: CompiledSimulationIR, world: Any, dt: float) -> dict[str, Any]:
    """Dispatch one compiled tick to the installed runtime backend."""
    executor = SIMULATION_EXECUTORS.get(compiled.backend.backend_id)
    execution_backend = compiled.backend.backend_id
    if executor is None or not compiled.backend.available:
        executor = SIMULATION_EXECUTORS.get("reference_cpu")
        execution_backend = "reference_cpu"
    if executor is None:
        raise RuntimeError(f"No runtime executor is registered for {compiled.backend.backend_id}.")
    actual_capabilities = BACKENDS.get(execution_backend, BACKENDS["reference_cpu"])
    compiled.metadata["execution_backend"] = execution_backend
    compiled.metadata["gpu_resident"] = bool(actual_capabilities.execution_device == "gpu")
    if execution_backend != compiled.backend.backend_id and not any(
        item.get("code") == "runtime_backend_fallback" for item in compiled.diagnostics
    ):
        compiled.diagnostics.append({
            "severity": "warning",
            "code": "runtime_backend_fallback",
            "message": f"Executed on {execution_backend}; {compiled.backend.backend_id} has no available executor.",
        })
    started = time.perf_counter()
    result = executor(compiled, world, float(dt))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    backend_receipt = dict(result or {}) if isinstance(result, dict) else {}
    telemetry = {
        "schema": "tech_connector.simulation_execution.v1",
        "compiled_backend": compiled.backend.backend_id,
        "execution_backend": execution_backend,
        "execution_device": actual_capabilities.execution_device,
        "gpu_resident": bool(compiled.metadata["gpu_resident"]),
        "elapsed_ms": elapsed_ms,
        "target_frame_ms": compiled.profile.target_frame_ms,
        "within_budget": elapsed_ms <= compiled.profile.target_frame_ms,
        "particle_count": len(getattr(world, "particles", ()) or ()),
        "stage_ms": dict(backend_receipt.get("stage_ms") or {"monolithic_reference": elapsed_ms}),
        "memory_bytes": int(backend_receipt.get("memory_bytes", 0) or 0),
        "backend_receipt": backend_receipt,
    }
    compiled.metadata["last_execution"] = telemetry
    history = list(compiled.metadata.get("execution_history") or [])
    history.append({key: value for key, value in telemetry.items() if key != "backend_receipt"})
    compiled.metadata["execution_history"] = history[-120:]
    return telemetry


register_simulation_executor("reference_cpu", execute_compiled_reference)


def effect_system_is_stateless(system: Any) -> bool:
    if (getattr(system, "event_bindings", None) or getattr(system, "data_channel_bindings", None)
            or getattr(system, "data_channel_consumers", None)):
        return False
    supported = {
        "initialize", "add_velocity", "rotation", "gravity", "drag", "vortex", "curl_noise",
        "orbit", "kill_box", "color_over_life", "size_over_life",
    }
    return all(
        str(module.module_type) in supported
        for emitter in getattr(system, "emitters", ()) or ()
        for module in getattr(emitter, "modules", ()) or ()
    )


def _select_backend(
    domains: list[str], profile: SimulationExecutionProfile, requested: str
) -> tuple[SimulationBackendCapabilities, list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    requested = str(requested or "auto").lower()
    if requested == "auto":
        # Auto compilation targets the native IR even when this installation has
        # no native executor. The compiled receipt remains production-shaped and
        # the diagnostic makes the execution limitation explicit. An explicitly
        # requested unavailable backend still falls back to the reference path.
        native = BACKENDS["native_cpu"]
        if set(domains) <= set(native.domains):
            diagnostics.append({
                "severity": "warning",
                "code": "production_backend_unavailable",
                "message": (
                    "Compiled native CPU IR; no native executor is installed in "
                    "this process, so live execution requires the reference backend."
                ),
            })
            return native, diagnostics
    candidates = [requested]
    for backend_id in candidates:
        candidate = BACKENDS.get(backend_id)
        if candidate and candidate.available and set(domains) <= set(candidate.domains):
            if backend_id == "reference_cpu" and requested != "reference_cpu":
                diagnostics.append({
                    "severity": "warning",
                    "code": "production_backend_unavailable",
                    "message": "Using the deterministic reference CPU backend; native/GPU execution is not installed yet.",
                })
            return candidate, diagnostics
    if requested != "auto":
        diagnostics.append({
            "severity": "warning",
            "code": "requested_backend_unavailable",
            "message": f"Requested backend {requested} is unavailable; using reference_cpu.",
        })
    return BACKENDS["reference_cpu"], diagnostics


def _simulation_domains(world: Any) -> list[str]:
    phases = {str(particle.phase) for particle in getattr(world, "particles", ()) or ()}
    domains: set[str] = set()
    if "cloth" in phases:
        domains.add("cloth")
    if phases & {"softbody", "reformable"}:
        domains.add("softbody")
    if "fluid" in phases:
        domains.add("fluid")
    if "rigid_cluster" in phases:
        domains.add("rigid")
    if phases - {"cloth", "softbody", "reformable", "fluid", "rigid_cluster"} or getattr(world, "emitters", None):
        domains.add("particle")
    if getattr(world, "volumes", None):
        domains.add("volume")
    if getattr(world, "effect_system", None) is not None:
        domains.add("effect")
        workflow = dict(getattr(world.effect_system, "workflow", {}) or {})
        workflow_domain = str(dict(workflow.get("solver", {}) or {}).get("domain", ""))
        if workflow_domain:
            domains.add(workflow_domain)
    if getattr(world, "deformable_surfaces", None):
        domains.add("surface")
    return sorted(domains or {"particle"})


def _compiled_outputs(domains: list[str], profile: SimulationExecutionProfile) -> list[dict[str, Any]]:
    outputs = [{"role": "runtime_state", "format": "tc.sim.buffers", "required": True}]
    if "volume" in domains:
        outputs.append({"role": "volume", "format": "tc.sparse_volume", "required": True})
    if set(domains) & {"cloth", "softbody", "rigid"}:
        outputs.append({"role": "deformation", "format": "tc.deformation_stream", "required": True})
    if "effect" in domains:
        outputs.append({"role": "render_streams", "format": f"tc.render.{profile.render_style}", "required": True})
        outputs.append({"role": "events", "format": "tc.runtime.event_stream", "required": True})
    return outputs
