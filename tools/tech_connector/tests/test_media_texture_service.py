"""Unified still-image, GIF, and video texture-source coverage."""

from __future__ import annotations

import pytest

from tech_connector.game_engine.rendering.media_texture_service import (
    infer_media_source_type,
    media_texture_runtime_capabilities,
    normalize_media_texture_source,
    plan_media_texture_residency,
    qualify_media_texture_source,
)
from tech_connector.game_engine.rendering.material_contract import (
    normalize_portable_material,
    viewer_material_approximation,
)
from tech_connector.ui.dcc_viewer.mesh_painter.workers import SceneProxyInstance, SceneProxyMaterialBinding


def test_media_type_inference_covers_images_gifs_and_video() -> None:
    assert infer_media_source_type("albedo.exr") == "image"
    assert infer_media_source_type("energy.GIF") == "animated_image"
    assert infer_media_source_type("https://assets.example/screen.webm?rev=2") == "video"
    assert infer_media_source_type("frames.bin", declared_type="gif") == "animated_image"


def test_media_playback_controls_are_normalized_and_validated(tmp_path) -> None:
    movie = tmp_path / "display.mp4"
    movie.write_bytes(b"test movie placeholder")
    source = normalize_media_texture_source({
        "path": str(movie),
        "autoplay": False,
        "loop": False,
        "playback": {
            "playback_rate": 0.5,
            "start_time_seconds": 2.0,
            "end_time_seconds": 8.0,
            "synchronization": "manual",
        },
    })

    assert source.source_type == "video"
    assert not source.autoplay and not source.loop
    assert source.playback_rate == 0.5
    assert source.start_time_seconds == 2.0
    assert source.end_time_seconds == 8.0
    assert qualify_media_texture_source(source)["qualified"]

    with pytest.raises(ValueError, match="end time"):
        normalize_media_texture_source({"path": str(movie), "start_time_seconds": 3, "end_time_seconds": 2})


def test_portable_material_preserves_animated_texture_intent() -> None:
    material = normalize_portable_material({
        "textures": {
            "base_color": {
                "path": "textures/screen.mp4",
                "playback": {"loop": True, "playback_rate": 1.25, "muted": True},
            },
            "emission": {"path": "textures/pulse.gif", "autoplay": False},
            "normal": "textures/normal.png",
        },
    }, source_path="C:/show/asset/look.usda")
    approximation = viewer_material_approximation(material)

    assert material.textures["base_color"].source_type == "video"
    assert material.textures["base_color"].playback["playback_rate"] == 1.25
    assert material.textures["emission_color"].source_type == "animated_image"
    assert not material.textures["emission_color"].playback["autoplay"]
    assert material.textures["normal"].source_type == "image"
    assert approximation["texture_sources"]["base_color"]["source_type"] == "video"


def test_missing_media_is_an_explicit_blocker_and_remote_media_is_a_warning(tmp_path) -> None:
    missing = qualify_media_texture_source({"path": str(tmp_path / "missing.gif")})
    remote = qualify_media_texture_source({"url": "https://example.invalid/screen.mp4"})

    assert not missing["qualified"] and "source_missing" in missing["blockers"]
    assert remote["qualified"]
    assert any("network" in warning for warning in remote["warnings"])
    assert media_texture_runtime_capabilities()["hardware_decode"] == "runtime_and_codec_dependent"


def test_scene_proxy_binding_and_playback_edit_preserve_media_source() -> None:
    material = SceneProxyMaterialBinding()
    proxy = SceneProxyInstance(0, "local", "screen", "Screen", materials=[material])

    proxy.bind_texture_source("base_color", {
        "path": "screen.gif", "autoplay": True, "loop": True,
    })
    edited = proxy.configure_texture_playback(
        "base_color", autoplay=False, playback_rate=0.75, synchronization="manual",
    )

    assert material.texture_paths["base_color"] == "screen.gif"
    assert material.texture_sources["base_color"]["source_type"] == "animated_image"
    assert not edited["autoplay"]
    assert edited["playback_rate"] == 0.75
    assert edited["synchronization"] == "manual"
    assert proxy.sync_state == "dirty"


def test_image_sequence_contract_and_qualification(tmp_path) -> None:
    first = tmp_path / "smoke.1001.png"
    first.write_bytes(b"frame")
    source = normalize_media_texture_source({
        "path": str(tmp_path / "smoke.####.png"),
        "sequence_start": 1001,
        "sequence_end": 1010,
        "sequence_padding": 4,
        "frame_rate": 24,
    })

    assert source.source_type == "image_sequence"
    assert source.sequence_start == 1001 and source.sequence_end == 1010
    assert qualify_media_texture_source(source)["qualified"]


def test_residency_plan_bounds_concurrent_video_decoders() -> None:
    plan = plan_media_texture_residency({
        "base_color": {"path": "a.mp4"},
        "emission": {"path": "b.webm"},
        "opacity": {"path": "mask.gif"},
        "normal": {"path": "normal.png"},
    }, maximum_video_decoders=1, maximum_animated_sources=2)

    assert plan["active_slots"] == ["base_color", "opacity", "normal"]
    assert plan["deferred_slots"] == ["emission"]
    assert not plan["budget_satisfied"]
