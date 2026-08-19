"""Capability-driven runtime recommendations for engine-facing simulation UX."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    BACKENDS,
    EXECUTION_PROFILES,
    compile_simulation_world,
)


@dataclass(frozen=True)
class EngineTargetProfile:
    target_id: str
    label: str
    frame_budget_ms: float
    tick_rate: int
    particle_budget: int
    preferred_backend: str
    default_quality: str
    supports_topology_changes: bool = True
    supports_sparse_volumes: bool = True


TARGET_PROFILES = {
    "desktop": EngineTargetProfile("desktop", "Desktop", 4.0, 60, 250_000, "gpu_compute", "realtime"),
    "console": EngineTargetProfile("console", "Console", 4.0, 60, 200_000, "gpu_compute", "realtime"),
    "mobile": EngineTargetProfile("mobile", "Mobile", 2.0, 30, 20_000, "gpu_compute", "mobile", False, False),
    "vr": EngineTargetProfile("vr", "VR", 2.0, 90, 75_000, "gpu_compute", "realtime", False, True),
    "web": EngineTargetProfile("web", "Web", 1.5, 30, 10_000, "gpu_compute", "retro", False, False),
    "cinematic": EngineTargetProfile("cinematic", "Offline / Cinematic", 33.3, 24, 2_000_000, "native_cpu", "cinematic"),
}

EXPERIENCE_GOALS = {
    "balanced": {"label": "Balanced", "quality": ""},
    "visual_fidelity": {"label": "Visual Fidelity", "quality": "photoreal"},
    "stable_frame_rate": {"label": "Stable Frame Rate", "quality": "mobile"},
    "stylized": {"label": "Stylized", "quality": "stylized"},
    "retro": {"label": "Retro / Simple", "quality": "retro"},
}


def build_engine_runtime_experience_plan(
    world: Any,
    *,
    target: str = "desktop",
    goal: str = "balanced",
    quality: str = "auto",
    backend: str = "auto",
    adaptive: bool = True,
    tick_rate: int | None = None,
) -> dict[str, Any]:
    """Turn user intent into an inspectable runtime configuration and fallback plan."""
    target_key = str(target).lower()
    goal_key = str(goal).lower()
    target_profile = TARGET_PROFILES.get(target_key)
    if target_profile is None:
        raise KeyError(f"Unknown engine target: {target}")
    if goal_key not in EXPERIENCE_GOALS:
        raise KeyError(f"Unknown runtime experience goal: {goal}")

    recommended_quality = (
        EXPERIENCE_GOALS[goal_key]["quality"] or target_profile.default_quality
    )
    quality_key = str(quality).strip().lower()
    if quality_key == "auto":
        selected_quality = recommended_quality
    elif quality_key not in EXECUTION_PROFILES:
        supported_qualities = ", ".join(sorted(EXECUTION_PROFILES.keys()))
        raise ValueError(
            f"Unknown runtime quality '{quality}'. Supported quality options: {supported_qualities}."
        )
    else:
        selected_quality = quality_key

    backend_key = str(backend).strip().lower()
    if backend_key == "auto":
        requested_backend = target_profile.preferred_backend
    elif backend_key not in BACKENDS:
        supported_backends = ", ".join(sorted(BACKENDS.keys()))
        raise ValueError(
            f"Unknown runtime backend '{backend}'. Supported backends: {supported_backends}, auto."
        )
    else:
        requested_backend = backend_key
    compiled = compile_simulation_world(world, profile=selected_quality, backend=requested_backend)
    domains = list(compiled.domains)
    capabilities = _feature_capabilities(domains, target_profile, compiled.backend.backend_id)
    fallback_count = sum(item["status"] == "fallback" for item in capabilities)
    blocked_count = sum(item["status"] == "blocked" for item in capabilities)
    controls = _adaptive_controls(domains)
    selected_tick_rate = max(1, int(tick_rate or target_profile.tick_rate))

    return {
        "schema": "tech_connector.engine_runtime_experience.v1",
        "target": asdict(target_profile),
        "goal": goal_key,
        "adaptive": bool(adaptive),
        "selection": {
            "quality": selected_quality,
            "backend_requested": requested_backend,
            "backend_resolved": compiled.backend.backend_id,
            "tick_rate": selected_tick_rate,
            "fixed_dt": 1.0 / selected_tick_rate,
            "frame_budget_ms": target_profile.frame_budget_ms,
            "particle_budget": target_profile.particle_budget,
            "current_particle_count": len(getattr(world, "particles", ()) or ()),
        },
        "recommendation": {
            "quality": recommended_quality,
            "backend": target_profile.preferred_backend,
            "tick_rate": target_profile.tick_rate,
        },
        "domains": domains,
        "features": capabilities,
        "visible_controls": controls,
        "fallback_count": fallback_count,
        "blocked_count": blocked_count,
        "ready": blocked_count == 0,
        "summary": _summary(compiled.backend.backend_id, selected_quality, fallback_count, blocked_count),
        "compiled_ir": compiled,
    }


def runtime_target_options() -> list[dict[str, Any]]:
    return [asdict(profile) for profile in TARGET_PROFILES.values()]


def runtime_goal_options() -> list[dict[str, str]]:
    return [{"id": key, "label": value["label"]} for key, value in EXPERIENCE_GOALS.items()]


def _feature_capabilities(
    domains: list[str], target: EngineTargetProfile, resolved_backend: str
) -> list[dict[str, str]]:
    backend = BACKENDS[resolved_backend]
    items: list[dict[str, str]] = []
    for domain in domains:
        status = "ready"
        path = "TC accelerated runtime" if resolved_backend != "reference_cpu" else "TC compatibility runtime"
        detail = "Runs natively through the selected TC runtime executor."
        if resolved_backend == "reference_cpu":
            status = "fallback"
            detail = "Correctness runtime is active; install a native CPU/GPU executor for production performance."
        if domain == "volume" and not target.supports_sparse_volumes:
            status, path = "fallback", "Baked volume/flipbook"
            detail = f"{target.label} disables live sparse volumes by default."
        if domain in {"cloth", "softbody", "rigid"} and not target.supports_topology_changes:
            status, path = "fallback", "Fixed-topology simulation"
            detail = f"Runtime tearing and fracture are disabled for {target.label}."
        items.append({"feature": domain, "runtime_path": path, "status": status, "detail": detail})
    renderer_status = "fallback" if resolved_backend == "reference_cpu" else "ready"
    items.append({
        "feature": "render_streams",
        "runtime_path": "TC renderer packets",
        "status": renderer_status,
        "detail": "Renderer packets are available; production GPU renderer integration remains target-specific." if renderer_status == "fallback" else "Renderer streams are runtime-ready.",
    })
    items.append({
        "feature": "events_and_gameplay",
        "runtime_path": "Deterministic event stream",
        "status": "ready",
        "detail": "Collision, death, and authored effect events can drive gameplay on fixed ticks.",
    })
    return items


def _adaptive_controls(domains: list[str]) -> list[str]:
    controls = ["quality", "target_frame_budget", "tick_rate", "backend", "adaptive_lod"]
    if "effect" in domains or "particle" in domains:
        controls.extend(["particle_budget", "spawn_scale", "renderer_budget"])
    if "cloth" in domains:
        controls.extend(["cloth_iterations", "self_collision", "tearing", "wrinkle_lod"])
    if "volume" in domains:
        controls.extend(["volume_resolution", "combustion", "volume_fallback"])
    if set(domains) & {"fluid", "softbody"}:
        controls.extend(["solver_substeps", "volume_preservation"])
    return list(dict.fromkeys(controls))


def _summary(backend: str, quality: str, fallbacks: int, blockers: int) -> str:
    if blockers:
        return f"{blockers} runtime feature(s) need attention before deployment."
    if fallbacks:
        return f"Ready to preview accurately; {fallbacks} production optimization(s) are still using compatible alternatives."
    return f"Ready to deploy using the {quality.replace('_', ' ')} quality profile."

