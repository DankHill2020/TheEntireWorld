import pytest

from tech_connector.services.dcc.engine_runtime_experience_service import (
    build_engine_runtime_experience_plan,
    runtime_goal_options,
    runtime_target_options,
)
from tech_connector.services.dcc.tc_effect_system_service import create_effect_world
from tech_connector.services.dcc.tc_engine_api import engine, engine_access_contract
from tech_connector.services.dcc.adaptive_scene_command_service import resolve_adaptive_scene_command
from tech_connector.services.dcc.tc_simulation_service import create_cloth_grid, create_sparse_fire_volume


def test_desktop_effect_setup_exposes_only_relevant_runtime_controls() -> None:
    plan = build_engine_runtime_experience_plan(
        create_effect_world("sparks"), target="desktop", goal="balanced"
    )

    assert plan["ready"] is True
    assert plan["selection"]["quality"] == "realtime"
    assert plan["selection"]["tick_rate"] == 60
    assert "spawn_scale" in plan["visible_controls"]
    assert "cloth_iterations" not in plan["visible_controls"]
    assert plan["selection"]["backend_resolved"] == "reference_cpu"
    assert plan["fallback_count"] > 0


def test_mobile_cloth_plan_makes_topology_fallback_visible() -> None:
    plan = build_engine_runtime_experience_plan(
        create_cloth_grid(3, 3), target="mobile", goal="stable_frame_rate"
    )

    cloth = next(item for item in plan["features"] if item["feature"] == "cloth")
    assert cloth["status"] == "fallback"
    assert cloth["runtime_path"] == "Fixed-topology simulation"
    assert "tearing" in plan["visible_controls"]


def test_web_volume_uses_a_visible_baked_fallback() -> None:
    plan = build_engine_runtime_experience_plan(
        create_sparse_fire_volume(), target="web", goal="retro"
    )

    volume = next(item for item in plan["features"] if item["feature"] == "volume")
    assert volume["runtime_path"] == "Baked volume/flipbook"
    assert plan["selection"]["tick_rate"] == 30


def test_runtime_setup_options_are_stable_for_ui_and_chat() -> None:
    assert {item["target_id"] for item in runtime_target_options()} >= {"desktop", "mobile", "vr", "web"}
    assert {item["id"] for item in runtime_goal_options()} >= {"balanced", "visual_fidelity", "stable_frame_rate"}


def test_code_api_uses_the_same_adaptive_runtime_plan_as_manual_and_chat() -> None:
    configured = engine.create_effect("sparks", target="mobile", goal="stable_frame_rate", seed=4)

    assert configured.plan["selection"]["quality"] == "mobile"
    assert configured.runtime.fixed_dt == 1.0 / 30.0
    assert configured.receipt()["deployment"]["requires_editor"] is False
    access = engine_access_contract()
    assert access["configure_runtime"]["command"] == "engine.configure_runtime"
    assert access["live_update"]["command"] == "engine.live_update_scene"
    route = resolve_adaptive_scene_command(
        "engine.configure_runtime",
        {"provider": "tech_connector", "native_id": "tcfx.sparks"},
        {"target": "mobile", "goal": "stable_frame_rate"},
    )
    assert route.status == "routable"
    assert route.required_payload["target"] == "mobile"


def test_runtime_plan_rejects_unknown_quality() -> None:
    with pytest.raises(ValueError, match=r"Unknown runtime quality 'ultravivid'"):
        build_engine_runtime_experience_plan(
            create_effect_world("sparks"),
            target="desktop",
            quality="ultravivid",
        )


def test_runtime_plan_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match=r"Unknown runtime backend 'faux_render'"):
        build_engine_runtime_experience_plan(
            create_sparse_fire_volume(),
            target="desktop",
            backend="faux_render",
        )
