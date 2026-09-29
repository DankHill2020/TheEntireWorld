from __future__ import annotations

"""Evidence-backed qualification for the realtime FX authoring/runtime slice."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any, Mapping, Sequence

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.integration.playable_project_qualification_service import playable_project_source_fingerprint
from tech_connector.game_engine.runtime.tc_effect_system_service import bake_effect_system, create_effect_world, set_effect_parameter
from tech_connector.game_engine.runtime.tc_fx_workflow_service import audit_fx_world, solver_profile_for_preset
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance


FX_QUALIFICATION_SCHEMA = "tech_connector.realtime_fx_qualification.v1"
DEFAULT_PRESETS = ("sparks", "rain", "refractive_bubbles", "mudslide", "avalanche", "earthquake", "fog", "jello", "ocean")
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0


def qualify_realtime_fx(
    source_root: str | Path, output_root: str | Path, *, presets: Sequence[str] = DEFAULT_PRESETS,
    frames: int = 120, frame_budget_ms: float = 16.667, maximum_particles: int = 2_048,
    maximum_preset_seconds: float = 8.0,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve(); output = Path(output_root).expanduser().resolve()
    run_id = f"run-{time.time_ns()}"; workspace = output / "runs" / run_id / "workspace"
    output.mkdir(parents=True, exist_ok=True); api = TCEditorAPI(workspace); rows: list[dict[str, Any]] = []
    for index, preset in enumerate(tuple(dict.fromkeys(str(value) for value in presets))):
        asset = api.create_effect_system(f"FX_{preset.title().replace('_', '')}", preset=preset, quality="realtime", seed=101 + index)
        issues = api.validate_effect_system(asset.asset_id, quality="realtime")
        cost = api.estimate_effect_cost(asset.asset_id, quality="realtime")
        first = api.cook_effect_system(asset.asset_id, quality="realtime"); first_bytes = first.path.read_bytes()
        second = api.cook_effect_system(asset.asset_id, quality="realtime"); second_bytes = second.path.read_bytes()
        first_world = create_effect_world(preset, quality="realtime", seed=101 + index)
        second_world = create_effect_world(preset, quality="realtime", seed=101 + index)
        for world in (first_world, second_world):
            set_effect_parameter(world.effect_system, "performance_contract.maximum_particles", max(1, int(maximum_particles)))
            for emitter in world.effect_system.emitters: emitter.max_particles = min(max(1, int(maximum_particles)), max(1, int(emitter.max_particles)))
        first_runtime = SimulationRuntimeInstance(first_world, profile="realtime", backend="gpu_compute", tick_rate=60.0)
        second_runtime = SimulationRuntimeInstance(second_world, profile="realtime", backend="gpu_compute", tick_rate=60.0)
        warmup_frames = min(10, max(1, int(frames) // 10))
        for _ in range(warmup_frames):
            first_runtime.advance(1.0 / 60.0)
            second_runtime.advance(1.0 / 60.0)
        # Shader/session creation belongs to warmup, not the steady-state
        # solver budget. Keep the timed receipt limited to the measured run.
        first_runtime.compiled.metadata["execution_history"] = []
        second_runtime.compiled.metadata["execution_history"] = []
        timings: list[float] = []
        runtime_started = time.perf_counter(); completed_frames = 0
        for _ in range(max(2, int(frames))):
            started = time.perf_counter(); first_runtime.advance(1.0 / 60.0); timings.append((time.perf_counter() - started) * 1000.0)
            second_runtime.advance(1.0 / 60.0); completed_frames += 1
            if time.perf_counter() - runtime_started > max(0.1, float(maximum_preset_seconds)): break
        first_world, second_world = first_runtime.world, second_runtime.world
        audit = audit_fx_world(first_world)
        first_health = first_runtime.health_snapshot()
        deterministic = _world_digest(first_world) == _world_digest(second_world)
        p95 = _percentile(timings, 0.95)
        solver_p95 = float(first_health.p95_ms)
        solver_frame_budget_ms = float(
            dict(first_world.effect_system.performance_contract or {}).get("target_frame_ms")
            or frame_budget_ms
        )
        surface_outputs = dict(getattr(first_world, "_native_surface_outputs", {}) or {})
        ocean_patches = list(surface_outputs.values()) if preset in {"ocean", "storm_ocean"} else []
        surface_render_output = bool(
            preset not in {"ocean", "storm_ocean"}
            or (
                ocean_patches
                and all(
                    len(dict(patch).get("vertices") or ()) == 32 * 32
                    and len(dict(patch).get("normals") or ()) == 32 * 32
                    and len(dict(patch).get("triangles") or ()) == 2 * 31 * 31
                    for patch in ocean_patches
                )
            )
        )
        checks = {
            "authoring_validation": not any(row.get("severity") == "error" for row in issues),
            "cost_budget": cost.get("status") != "over_budget",
            "deterministic_cook": first_bytes == second_bytes,
            "deterministic_runtime": deterministic,
            "completed_frames": completed_frames == max(2, int(frames)),
            "runtime_audit": audit.status != "error",
            "particle_budget": int(audit.metrics.get("particles") or 0) <= int(audit.metrics.get("particle_budget") or 0),
            "frame_budget": p95 <= float(frame_budget_ms),
            # The authored solver budget applies to backend execution. The
            # independent frame budget above covers packet construction,
            # deterministic hashing, and all other runtime overhead.
            "solver_frame_budget": solver_p95 <= solver_frame_budget_ms,
            "surface_render_output": surface_render_output,
        }
        requested_backend = str(audit.metrics.get("requested_backend") or "")
        effective_backend = str(audit.metrics.get("effective_preview_backend") or "")
        actual_backend = str(first_health.execution_backend or "")
        gpu_backend_qualified = bool(
            requested_backend in {"auto", "gpu_compute"}
            and actual_backend == "gpu_compute"
            and not first_health.fallback_active
            and audit.metrics.get("backend_available")
            and not any(item.get("code") == "backend_fallback" for item in audit.diagnostics)
        )
        production_backend_qualified = bool(
            actual_backend in {"native_cpu", "gpu_compute"}
            and not first_health.fallback_active
            and solver_p95 <= solver_frame_budget_ms
        )
        rows.append({
            "preset": preset, "solver_profile": solver_profile_for_preset(preset).profile_id,
            "status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "frame_ms": {"average": statistics.fmean(timings), "p95": p95, "maximum": max(timings)},
            "solver_frame_ms": {
                "average": float(first_health.average_ms), "p95": solver_p95,
            },
            "solver_frame_budget_ms": solver_frame_budget_ms,
            "completed_frames": completed_frames,
            "warmup_frames": warmup_frames,
            "live_particles": int(audit.metrics.get("particles") or 0), "cost": cost,
            "surface_outputs": {
                "count": len(surface_outputs),
                "vertices": sum(len(dict(item).get("vertices") or ()) for item in surface_outputs.values()),
                "triangles": sum(len(dict(item).get("triangles") or ()) for item in surface_outputs.values()),
            },
            "diagnostics": list(audit.diagnostics), "cook_sha256": hashlib.sha256(first_bytes).hexdigest(),
            "backend": {
                "requested": requested_backend,
                "compiled": effective_backend,
                "executed": actual_backend,
                "execution_device": first_health.execution_device,
                "fallback_active": bool(first_health.fallback_active),
                "gpu_resident": bool(first_health.gpu_resident),
                "available": bool(audit.metrics.get("backend_available")),
                "compiled_domains": list(audit.metrics.get("compiled_domains") or ()),
                "supported_domains": list(audit.metrics.get("backend_domains") or ()),
                "gpu_qualified": gpu_backend_qualified,
                "production_qualified": production_backend_qualified,
            },
        })
    cache = bake_effect_system(create_effect_world("sparks", quality="realtime", seed=7), start_frame=1, end_frame=3)
    recovery_checks = {
        "resumable_cache": cache.resumable_frame("simulate") is not None,
        "checkpoint_frame": int(cache.metadata.get("checkpoints", {}).get("simulate") or 0) == 3,
    }
    covered = sorted({row["solver_profile"] for row in rows if row["status"] == "passed"})
    gpu_qualified_presets = sorted(row["preset"] for row in rows if row["backend"]["gpu_qualified"])
    gpu_unqualified_presets = sorted(row["preset"] for row in rows if not row["backend"]["gpu_qualified"])
    production_qualified_presets = sorted(row["preset"] for row in rows if row["backend"]["production_qualified"])
    production_unqualified_presets = sorted(row["preset"] for row in rows if not row["backend"]["production_qualified"])
    receipt = {
        "schema": FX_QUALIFICATION_SCHEMA,
        "status": "passed" if rows and all(row["status"] == "passed" for row in rows) and all(recovery_checks.values()) else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
        "source_fingerprint": playable_project_source_fingerprint(source),
        "frames": max(2, int(frames)), "frame_budget_ms": float(frame_budget_ms),
        "maximum_particles": max(1, int(maximum_particles)), "maximum_preset_seconds": float(maximum_preset_seconds),
        "covered_solver_profiles": covered,
        "unqualified_solver_profiles": sorted({"particle_realtime", "flip_liquid", "viscous_goop", "granular", "softbody", "destruction", "sparse_pyro", "ocean_surface"} - set(covered)),
        "gpu_qualification": {
            "qualified": bool(rows) and not gpu_unqualified_presets,
            "qualified_presets": gpu_qualified_presets,
            "unqualified_presets": gpu_unqualified_presets,
        },
        "production_backend_qualification": {
            "qualified": bool(rows) and not production_unqualified_presets,
            "qualified_presets": production_qualified_presets,
            "unqualified_presets": production_unqualified_presets,
        },
        "qualified_asset_types": ["tc.effect_system"] if rows and all(row["status"] == "passed" for row in rows) else [],
        "recovery_checks": recovery_checks, "presets": rows,
    }
    report = output / "realtime_fx_qualification.json"; temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"); temporary.replace(report)
    return receipt | {"report": str(report)}


def validate_realtime_fx_qualification(
    source_root: str | Path,
    receipt: Mapping[str, Any] | None,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    require_gpu_backend: bool = False,
    require_production_backend: bool = False,
) -> dict[str, Any]:
    row = dict(receipt or {}); gates: list[str] = []
    if row.get("schema") != FX_QUALIFICATION_SCHEMA: gates.append("schema")
    if row.get("status") != "passed": gates.append("status")
    if not row.get("presets") or any(dict(item).get("status") != "passed" for item in row.get("presets") or ()): gates.append("presets")
    if not all(dict(row.get("recovery_checks") or {}).values()): gates.append("recovery")
    if require_gpu_backend and not bool(dict(row.get("gpu_qualification") or {}).get("qualified")):
        gates.append("gpu_backend")
    if require_production_backend and not bool(
        dict(row.get("production_backend_qualification") or {}).get("qualified")
    ):
        gates.append("production_backend")
    verified = _timestamp(row.get("verified_at")); now = datetime.now(timezone.utc).timestamp()
    if verified <= 0.0 or now - verified > max(0.0, float(max_age_seconds)): gates.append("freshness")
    expected = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected: gates.append("source_fingerprint")
    return {"valid": not gates, "gates": sorted(set(gates)), "age_seconds": max(0.0, now - verified) if verified > 0 else None,
            "source_fingerprint": expected, "gpu_backend_required": bool(require_gpu_backend),
            "production_backend_required": bool(require_production_backend)}


def load_realtime_fx_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file(): return {}
    try: value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return dict(value) if isinstance(value, dict) else {}


def _world_digest(world: Any) -> str:
    payload: dict[str, Any] = {"particles": [
        {"id": int(item.particle_id), "alive": bool(item.alive), "position": [round(float(value), 9) for value in item.position],
         "velocity": [round(float(value), 9) for value in item.velocity]} for item in world.particles
    ], "surfaces": [surface.to_dict() for surface in getattr(world, "deformable_surfaces", ()) if hasattr(surface, "to_dict")]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999999) - 1))] if ordered else 0.0


def _timestamp(value: Any) -> float:
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return 0.0


__all__ = ["DEFAULT_PRESETS", "FX_QUALIFICATION_SCHEMA", "load_realtime_fx_qualification", "qualify_realtime_fx", "validate_realtime_fx_qualification"]
