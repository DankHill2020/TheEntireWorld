from __future__ import annotations

from tech_connector.game_engine.integration.adaptive_scene_command_service import (
    ADAPTIVE_SCENE_COMMANDS,
    AdaptiveSceneCommand,
    list_adaptive_scene_commands,
)
from tech_connector.game_engine.integration.capability_maturity_service import (
    CapabilityEvidence,
    assess_capability,
    audit_capability_maturity,
)


def test_existing_implemented_flag_does_not_imply_production_readiness() -> None:
    emission = assess_capability(ADAPTIVE_SCENE_COMMANDS["simulation.paint_emission_source"])
    virtual_geometry = assess_capability(ADAPTIVE_SCENE_COMMANDS["engine.compile_virtualized_hard_surface"])

    assert emission.verified_maturity == "interactive"
    assert emission.next_maturity == "production"
    assert "native_backend" in emission.missing_gates
    assert virtual_geometry.verified_maturity == "production"
    assert virtual_geometry.next_maturity == "qualified"
    assert "golden_scenes" in virtual_geometry.missing_gates


def test_qualification_requires_native_performance_recovery_golden_stress_and_platform_evidence() -> None:
    command = AdaptiveSceneCommand(
        key="test.qualified",
        label="Qualified Test",
        department="test",
        subjects=("test",),
        tc_native_status="implemented",
    )
    evidence = CapabilityEvidence(
        capability=command.key,
        local_executor=True,
        deterministic_tests=("determinism",),
        user_entry_points=("ui", "api", "chat"),
        persistence_tests=("round_trip",),
        transfer_readback_tests=("unreal_readback",),
        native_backend="gpu_compute",
        performance_baselines=("frame_budget",),
        recovery_tests=("undo", "crash_recovery"),
        golden_scenes=("golden_scene",),
        stress_tests=("large_world",),
        qualified_platforms=("windows", "macos"),
    )

    assessment = assess_capability(command, evidence)

    assert assessment.verified_maturity == "qualified"
    assert not assessment.next_maturity
    assert not assessment.missing_gates


def test_command_catalog_and_audit_expose_verified_maturity() -> None:
    rows = list_adaptive_scene_commands()
    audit = audit_capability_maturity(ADAPTIVE_SCENE_COMMANDS.values())

    assert all("verified_maturity" in row for row in rows)
    assert sum(audit["counts"].values()) == len(ADAPTIVE_SCENE_COMMANDS)
    assert audit["declared_implemented"] > audit["production_ready"]
    assert audit["declaration_gap"] > 0
    maturity_command = next(row for row in rows if row["key"] == "engine.audit_capability_maturity")
    assert maturity_command["verified_maturity"] == "interactive"
