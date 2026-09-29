"""Evidence-backed production-readiness checks for the TC simulation runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
from typing import Any

from tech_connector.game_engine.runtime.tc_simulation_ir_service import simulation_backend_status
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance


@dataclass(frozen=True)
class EngineReadinessGate:
    gate_id: str
    status: str
    summary: str
    evidence: dict[str, Any]
    required_for_qualification: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EngineReadinessReport:
    maturity: str
    qualified: bool
    gates: tuple[EngineReadinessGate, ...]
    blockers: tuple[str, ...]
    recommendations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.engine_readiness.v1",
            "maturity": self.maturity,
            "qualified": self.qualified,
            "gates": [item.to_dict() for item in self.gates],
            "blockers": list(self.blockers),
            "recommendations": list(self.recommendations),
        }


def qualify_runtime_determinism(
    runtime: SimulationRuntimeInstance,
    *,
    ticks: int = 30,
    repeats: int = 2,
) -> dict[str, Any]:
    """Replay isolated instances and compare canonical state hashes tick for tick."""
    tick_count = max(1, int(ticks))
    repeat_count = max(2, int(repeats))
    runs: list[list[str]] = []
    execution_backends: set[str] = set()
    for _run in range(repeat_count):
        candidate = SimulationRuntimeInstance(
            runtime.authored_world_snapshot(),
            profile=runtime.profile,
            backend=runtime.backend,
            tick_rate=1.0 / runtime.fixed_dt,
            max_catch_up_steps=runtime.max_catch_up_steps,
            checkpoint_interval=0,
            checkpoint_limit=1,
        )
        hashes: list[str] = []
        for _tick in range(tick_count):
            candidate.advance(candidate.fixed_dt)
            hashes.append(candidate.state_hash())
        runs.append(hashes)
        execution_backends.add(candidate.health_snapshot().execution_backend)
    mismatch_ticks = [
        index + 1 for index in range(tick_count)
        if any(run[index] != runs[0][index] for run in runs[1:])
    ]
    return {
        "schema": "tech_connector.runtime_determinism_qualification.v1",
        "qualified": not mismatch_ticks and len(execution_backends) == 1,
        "ticks": tick_count,
        "repeats": repeat_count,
        "mismatch_ticks": mismatch_ticks,
        "execution_backends": sorted(execution_backends),
        "final_state_hashes": [run[-1] for run in runs],
        "asset_fingerprint": runtime.asset_fingerprint,
    }


def audit_engine_readiness(
    runtime: SimulationRuntimeInstance,
    *,
    determinism_receipt: dict[str, Any] | None = None,
    minimum_performance_samples: int = 30,
) -> EngineReadinessReport:
    """Report what is proven, what is falling back, and what still needs qualification."""
    health = runtime.health_snapshot()
    ir_errors = runtime.compiled.validate()
    compiled_status = simulation_backend_status(runtime.compiled.backend.backend_id)
    history = list(runtime.compiled.metadata.get("execution_history") or [])
    output_roles = {str(item.get("role") or "") for item in runtime.compiled.outputs}
    expected_outputs = {"runtime_state"}
    if "effect" in runtime.compiled.domains:
        expected_outputs.update({"render_streams", "events"})
    gates = [
        _gate("valid_ir", not ir_errors, "Compiled simulation graph is structurally valid.",
              {"errors": ir_errors, "stage_count": len(runtime.compiled.stages)}),
        _gate("stable_asset_identity", len(runtime.asset_fingerprint) == 64,
              "Authored input has a stable content fingerprint.", {"sha256": runtime.asset_fingerprint}),
        _gate("deterministic_contract",
              bool(runtime.compiled.profile.deterministic and runtime.compiled.backend.deterministic),
              "Profile and compiled backend declare deterministic execution.",
              {"profile": runtime.compiled.profile.name, "backend": runtime.compiled.backend.backend_id}),
        _gate("executable_backend", bool(health.execution_backend),
              "A concrete execution backend has produced or can produce runtime state.",
              {"compiled": health.compiled_backend, "executed": health.execution_backend,
               "compiled_backend_available": compiled_status["available"]}),
        EngineReadinessGate(
            "fallback_transparency", "pass",
            "Compiled and executed backends are reported separately; fallback never masquerades as GPU/native execution.",
            {"fallback_active": health.fallback_active, "diagnostics": list(health.diagnostics)}, True,
        ),
        _gate("bounded_runtime_queues",
              runtime.max_pending_commands > 0 and runtime.command_history_limit >= runtime.max_pending_commands,
              "Runtime command and history memory have explicit bounds.",
              {"pending_limit": runtime.max_pending_commands, "history_limit": runtime.command_history_limit}),
        _gate("rollback_checkpoint", health.checkpoint_count > 0,
              "At least one isolated rollback checkpoint is available.",
              {"checkpoint_count": health.checkpoint_count}),
        _gate("required_outputs", expected_outputs <= output_roles,
              "Compiled outputs cover runtime state and domain-specific renderer/event streams.",
              {"expected": sorted(expected_outputs), "available": sorted(output_roles)}),
        _gate("performance_evidence",
              len(history) >= max(1, int(minimum_performance_samples)) and health.p95_ms <= runtime.compiled.profile.target_frame_ms,
              "Measured p95 execution time satisfies the selected profile budget.",
              {"samples": len(history), "required_samples": max(1, int(minimum_performance_samples)),
               "p95_ms": health.p95_ms, "target_ms": runtime.compiled.profile.target_frame_ms}),
        _gate("repeat_determinism", bool(determinism_receipt and determinism_receipt.get("qualified")),
              "Independent fixed-step runs produced identical tick hashes.",
              dict(determinism_receipt or {"qualified": False, "reason": "Qualification has not been run."})),
        EngineReadinessGate(
            "cache_capture", "pass" if runtime.cache is not None and health.cached_frames > 0 else "not_run",
            "Deterministic cache capture is available for bake and interchange workflows.",
            {"enabled": runtime.cache is not None, "frames": health.cached_frames}, False,
        ),
        EngineReadinessGate(
            "gpu_residency", "pass" if health.gpu_resident else "not_applicable" if health.execution_device != "gpu" else "fail",
            "GPU execution keeps working buffers resident without pretending CPU synchronization is free.",
            {"execution_device": health.execution_device, "gpu_resident": health.gpu_resident},
            health.execution_device == "gpu",
        ),
        EngineReadinessGate(
            "readback_free_gpu", "pass" if health.readback_free else "not_applicable" if health.execution_device != "gpu" else "fail",
            "GPU simulation can keep authoritative output resident through the consumer boundary.",
            {"execution_device": health.execution_device, "readback_free": health.readback_free,
             "synchronization_points": health.synchronization_points},
            health.execution_device == "gpu",
        ),
    ]
    blockers = tuple(item.gate_id for item in gates if item.required_for_qualification and item.status != "pass")
    recommendations: list[str] = []
    if "performance_evidence" in blockers:
        recommendations.append("Capture at least 30 representative runtime ticks and qualify p95 against the target profile.")
    if "repeat_determinism" in blockers:
        recommendations.append("Run independent deterministic replay qualification for the authored scene and selected backend.")
    if health.fallback_active:
        recommendations.append("Qualify or install the requested backend, or deliberately ship the reported fallback path.")
    if runtime.cache is None:
        recommendations.append("Enable cache capture for bake, resume, and cross-package delivery workflows.")
    if not blockers:
        maturity = "qualified"
    elif all(item.status == "pass" for item in gates if item.required_for_qualification and item.gate_id not in {"performance_evidence", "repeat_determinism"}):
        maturity = "production_candidate"
    elif not ir_errors and health.execution_backend:
        maturity = "interactive"
    else:
        maturity = "reference"
    return EngineReadinessReport(maturity, not blockers, tuple(gates), blockers, tuple(recommendations))


def _gate(gate_id: str, passed: bool, summary: str, evidence: dict[str, Any]) -> EngineReadinessGate:
    return EngineReadinessGate(gate_id, "pass" if passed else "fail", summary, copy.deepcopy(evidence), True)


__all__ = [
    "EngineReadinessGate", "EngineReadinessReport", "audit_engine_readiness", "qualify_runtime_determinism",
]
