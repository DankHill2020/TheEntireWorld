from __future__ import annotations

from tech_connector.game_engine.rendering.upscaling_service import (
    choose_upscaling_backend,
    create_upscaling_profile,
    required_frame_resources,
)


def test_quality_profile_produces_stable_internal_resolution() -> None:
    profile = create_upscaling_profile(backend="tc_temporal", quality="quality", output_width=3840, output_height=2160)
    assert profile.to_dict()["render_width"] == 2560
    assert profile.to_dict()["render_height"] == 1440
    assert "motion_vectors" in required_frame_resources("tc_temporal")


def test_vendor_backend_falls_back_when_api_or_runtime_is_unavailable() -> None:
    backend, reasons = choose_upscaling_backend("fsr", graphics_api="d3d11", installed_runtimes=("fidelityfx",))
    assert backend == "tc_temporal"
    assert reasons

    backend, reasons = choose_upscaling_backend("xess", graphics_api="d3d11", installed_runtimes=("xess",))
    assert backend == "xess"
    assert not reasons
