from __future__ import annotations

import math
import pytest

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.runtime.tc_effect_system_service import create_effect_world
from tech_connector.game_engine.runtime.tc_ocean_surface_service import create_ocean_surface
from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance
from tech_connector.game_engine.runtime.tc_simulation_service import signed_mesh_volume


def test_ocean_surface_is_deterministic_normalized_and_wake_aware() -> None:
    first = create_ocean_surface("open_ocean", seed=42)
    second = create_ocean_surface("open_ocean", seed=42)
    assert first.sample(2.0, -3.0).to_dict() == second.sample(2.0, -3.0).to_dict()
    sample = first.sample(2.0, -3.0)
    assert math.sqrt(sum(value * value for value in sample.normal)) == pytest.approx(1.0)
    before = first.sample(0.25, 0.0).position[1]
    first.add_wake((0.0, 0.0), (1.0, 0.0), radius=1.0, strength=0.5, lifetime=1.0)
    after = first.sample(0.25, 0.0).position[1]
    assert after != pytest.approx(before)
    first.step(1.1)
    assert first.wakes == []


def test_ocean_patch_has_renderable_topology_and_bounded_resolution() -> None:
    ocean = create_ocean_surface("storm", seed=3)
    patch = ocean.mesh_patch(rows=8, columns=9, size=30.0)
    assert len(patch["vertices"]) == 72
    assert len(patch["normals"]) == 72
    assert len(patch["foam"]) == 72
    assert len(patch["triangles"]) == 2 * 7 * 8
    assert all(0.0 <= value <= 1.0 for value in patch["foam"])


def test_ocean_runtime_uses_native_renderable_surface_output() -> None:
    runtime = SimulationRuntimeInstance(
        create_effect_world("ocean", quality="realtime", seed=9),
        profile="realtime", backend="gpu_compute", tick_rate=60.0,
    )
    packet = runtime.advance(1.0 / 60.0)
    health = runtime.health_snapshot()
    assert health.compiled_backend == "native_cpu"
    assert health.execution_backend == "native_cpu"
    assert health.fallback_active is False
    surfaces = packet.streams["ocean_surface"]
    assert len(surfaces) == 1
    assert len(surfaces[0]["mesh"]["vertices"]) == 32 * 32
    assert len(surfaces[0]["mesh"]["triangles"]) == 2 * 31 * 31


def test_softbody_and_ocean_presets_execute_real_simulation_domains() -> None:
    jello = create_effect_world("jello", quality="realtime", seed=7)
    ocean = create_effect_world("ocean", quality="realtime", seed=7)
    assert len(jello.particles) == 8 and len(jello.volume_constraints) == 1
    assert {particle.phase for particle in jello.particles} == {"softbody"}
    assert jello.substeps == 3
    assert jello.constraint_iterations == 3
    assert len(ocean.deformable_surfaces) == 1
    assert {"softbody", "effect"} <= set(compile_simulation_world(jello, backend="reference_cpu").domains)
    assert {"surface", "effect"} <= set(compile_simulation_world(ocean, backend="reference_cpu").domains)
    for _ in range(10): jello.step(1.0 / 60.0); ocean.step(1.0 / 60.0)
    assert all(math.isfinite(value) for particle in jello.particles for value in particle.position)
    current_volume = abs(signed_mesh_volume(
        [particle.position for particle in jello.particles], jello.surface_faces,
    ))
    rest_volume = abs(jello.volume_constraints[0].rest_volume)
    assert current_volume == pytest.approx(rest_volume, rel=0.08)
    assert ocean.deformable_surfaces[0].time_seconds == pytest.approx(10.0 / 60.0)


def test_python_api_authors_softbody_and_ocean_without_ui(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    ocean = api.create_ocean_surface("calm", seed=5, wave_count=6)
    api.add_ocean_wake(ocean, (0.0, 0.0), (2.0, 0.0))
    sample = api.sample_ocean_surface(ocean, 0.2, 0.0)
    patch = api.generate_ocean_patch(ocean, rows=4, columns=4)
    assert sample["normal"][1] > 0.0
    assert len(patch["vertices"]) == 16
    contract = api.capability_contract()
    assert contract["simulation_authoring_operations"] == [
        "create_runtime_soft_body", "create_ocean_surface", "sample_ocean_surface",
        "generate_ocean_patch", "add_ocean_wake",
    ]


def test_softbody_and_ocean_effect_assets_validate_and_cook(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    for preset in ("jello", "ocean", "storm_ocean"):
        asset = api.create_effect_system(f"FX_{preset}", preset=preset, quality="realtime")
        assert api.validate_effect_system(asset.asset_id, quality="realtime") == []
        assert api.cook_effect_system(asset.asset_id, quality="realtime").path.is_file()
