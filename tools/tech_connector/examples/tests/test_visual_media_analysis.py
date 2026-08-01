from pathlib import Path

from PIL import Image

from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.services.art_intelligence_service import (
    analyze_image_art_context,
    collect_visual_media_paths,
    generate_image_edit_artifacts,
)


def _solid_image(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (32, 24), color).save(path)
    return path


def test_image_analysis_uses_real_pixels(tmp_path):
    dark = _solid_image(tmp_path / "dark.png", (8, 8, 8))
    bright = _solid_image(tmp_path / "bright.png", (240, 240, 240))

    dark_result = analyze_image_art_context(str(dark), "analyze this image")
    bright_result = analyze_image_art_context(str(bright), "analyze this image")

    assert dark_result.image_id == str(dark)
    assert bright_result.image_id == str(bright)
    assert dark_result.evidence["mean_luma"] < bright_result.evidence["mean_luma"]
    assert dark_result.summary != bright_result.summary


def test_engine_requires_attached_visual_media(tmp_path):
    image = _solid_image(tmp_path / "render.png", (40, 80, 160))
    engine = RequestEngine()

    no_media = engine._fast_art_visual_intelligence_request_v2(
        RequestContext(text="analyze this render")
    )
    with_media = engine._fast_art_visual_intelligence_request_v2(
        RequestContext(text="analyze this render", attached_images=(str(image),))
    )

    assert no_media is None
    assert with_media is not None
    assert with_media.metadata["result_type"] == "visual_media_analysis"
    assert with_media.metadata["visual_ingestion"]["image_id"] == str(image)
    assert with_media.metadata["model_role"] == "visual_media"
    assert "coder" not in with_media.metadata["model_name"]
    assert "Measured Evidence" in with_media.text


def test_camera_setting_prompt_adds_camera_profile_and_chat_section(tmp_path):
    image = _solid_image(tmp_path / "camera_ref.png", (70, 95, 140))
    engine = RequestEngine()

    result = engine._fast_art_visual_intelligence_request_v2(
        RequestContext(
            text="review camera lens, FOV, aperture, depth of field, exposure, and safe frame",
            attached_images=(str(image),),
        )
    )

    assert result is not None
    ingestion = result.metadata["visual_ingestion"]
    camera_profile = ingestion["camera_spec"]["settings_profile"]
    assert camera_profile["requested"] is True
    assert "lens_focal_length" in camera_profile["matched_features"]
    assert "aperture_depth_of_field" in camera_profile["matched_features"]
    assert "exposure_shutter_iso" in camera_profile["matched_features"]
    assert "framing_aspect_resolution" in camera_profile["matched_features"]
    assert "Camera Settings / Shot Setup" in result.text
    assert "CineCameraActor" in result.text
    assert "cameraShape.focalLength" in result.text


def test_image_map_generation_creates_artifacts(tmp_path):
    source = _solid_image(tmp_path / "source.png", (40, 80, 160))

    result = generate_image_edit_artifacts(
        str(source),
        "create normal map and depth map",
        output_dir=tmp_path / "maps",
    )

    assert len(result.files_created) == 2
    assert any(path.endswith("_normal_map.png") for path in result.files_created)
    assert any(path.endswith("_depth_map.png") for path in result.files_created)
    assert all(Path(path).exists() for path in result.files_created)
    assert {artifact["type"] for artifact in result.artifacts} == {"normal_map", "depth_map"}


def test_engine_image_edit_prompt_returns_created_files(tmp_path):
    image = _solid_image(tmp_path / "render.png", (80, 100, 120))
    engine = RequestEngine()

    result = engine._fast_art_visual_intelligence_request_v2(
        RequestContext(text="create a normal map and roughness map", attached_images=(str(image),))
    )

    assert result is not None
    assert result.label == "Image Edit / Map Generation"
    assert result.metadata["result_type"] == "image_edit_artifacts"
    assert result.metadata["model_role"] == "visual_media"
    assert "coder" not in result.metadata["model_name"]
    assert len(result.metadata["files_created"]) == 2
    assert "Files Created" in result.text


def test_image_edit_operations_cover_texture_and_utility_fixes(tmp_path):
    source = _solid_image(tmp_path / "source.png", (80, 100, 120))

    result = generate_image_edit_artifacts(
        str(source),
        "crop 16x16 resize 32x32 remove background channel pack ORM convert webp "
        "color correct seamless tile contact sheet before/after",
        output_dir=tmp_path / "utility",
    )

    artifact_types = {artifact["type"] for artifact in result.artifacts}
    assert {
        "center_crop",
        "resize",
        "background_mask",
        "channel_pack_orm",
        "format_convert",
        "color_correct",
        "seamless_tile",
        "contact_sheet",
        "before_after",
    }.issubset(artifact_types)
    assert all(Path(path).exists() for path in result.files_created)
    assert any(path.endswith(".webp") for path in result.files_created)


def test_semantic_cutout_prompt_uses_semantic_operation_with_fallback(tmp_path, monkeypatch):
    import sys
    import tech_connector.services.art_intelligence_service as visual_service

    monkeypatch.setenv("TECH_CONNECTOR_DISABLE_SEGMENTATION_AUTO_INSTALL", "1")
    monkeypatch.setitem(sys.modules, "rembg", None)
    visual_service._SEGMENTATION_AUTO_INSTALL_ATTEMPTED = False
    source = _solid_image(tmp_path / "subject.png", (120, 120, 120))

    result = generate_image_edit_artifacts(
        str(source),
        "create a semantic object cutout with transparent background",
        output_dir=tmp_path / "cutout",
    )

    assert result.operation == "semantic_cutout"
    assert len(result.files_created) == 1
    assert result.files_created[0].endswith("_semantic_cutout.png")
    assert Path(result.files_created[0]).exists()
    assert result.artifacts[0]["type"] == "semantic_cutout"
    assert any("fallback" in warning.lower() for warning in result.warnings)


def test_engine_batches_image_edit_requests_over_multiple_images(tmp_path):
    first = _solid_image(tmp_path / "first.png", (20, 40, 60))
    second = _solid_image(tmp_path / "second.png", (200, 180, 120))
    engine = RequestEngine()

    result = engine._fast_art_visual_intelligence_request_v2(
        RequestContext(
            text="generate edge map",
            attached_images=(str(first), str(second)),
        )
    )

    assert result is not None
    assert result.metadata["result_type"] == "image_edit_artifacts"
    assert len(result.metadata["image_edit_results"]) == 2
    assert len(result.metadata["files_created"]) == 2
    assert all(Path(path).exists() for path in result.metadata["files_created"])


def test_collect_visual_media_paths_finds_videos_from_attached_files(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    context = RequestContext(
        text="review this video",
        extras={"attached_files": (str(video),)},
    )

    assert collect_visual_media_paths(context) == [str(video)]


def test_video_analysis_is_honest_when_decoder_unavailable_or_file_invalid(tmp_path, monkeypatch):
    import tech_connector.services.art_intelligence_service as visual_service

    monkeypatch.setenv("TECH_CONNECTOR_DISABLE_MEDIA_AUTO_INSTALL", "1")
    visual_service._MEDIA_AUTO_INSTALL_ATTEMPTED = False
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    result = analyze_image_art_context(str(video), "review this video")

    assert result.media_type == "video"
    assert result.evidence["sampled_frame_count"] == 0
    assert result.confidence <= 0.22
    assert "frame-level visual claims were not made" in " ".join(result.uncertainties)


def test_video_workflow_prompts_get_specific_ui_next_steps(tmp_path, monkeypatch):
    import tech_connector.services.art_intelligence_service as visual_service

    monkeypatch.setenv("TECH_CONNECTOR_DISABLE_MEDIA_AUTO_INSTALL", "1")
    visual_service._MEDIA_AUTO_INSTALL_ATTEMPTED = False
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")
    engine = RequestEngine()

    cases = [
        ("video to MetaHuman", "MetaHuman flow"),
        ("video mocap cleanup", "Mocap flow"),
        ("video tracking solve", "Tracking flow"),
        ("video editing for the shot", "Editing flow"),
    ]

    for prompt, expected in cases:
        result = engine._fast_art_visual_intelligence_request_v2(
            RequestContext(text=prompt, extras={"attached_files": (str(video),)})
        )

        assert result is not None
        assert result.metadata["visual_ingestion"]["media_type"] == "video"
        assert "Recommended Next Checks" in result.text
        assert expected in result.text


def test_video_camera_prompt_includes_stability_and_matchmove_controls(tmp_path, monkeypatch):
    import tech_connector.services.art_intelligence_service as visual_service

    monkeypatch.setenv("TECH_CONNECTOR_DISABLE_MEDIA_AUTO_INSTALL", "1")
    visual_service._MEDIA_AUTO_INSTALL_ATTEMPTED = False
    video = tmp_path / "plate.mov"
    video.write_bytes(b"not a real video")
    engine = RequestEngine()

    result = engine._fast_art_visual_intelligence_request_v2(
        RequestContext(
            text="review this camera track plate for lens distortion, matchmove, stabilization, shutter, and motion blur",
            extras={"attached_files": (str(video),)},
        )
    )

    assert result is not None
    camera_profile = result.metadata["visual_ingestion"]["camera_spec"]["settings_profile"]
    assert camera_profile["requested"] is True
    assert "matchmove_tracking" in camera_profile["matched_features"]
    assert "clipping_camera_rig" in camera_profile["matched_features"]
    assert "exposure_shutter_iso" in camera_profile["matched_features"]
    assert "Camera Settings / Shot Setup" in result.text
    assert "camera stability" in result.text
    assert "Camera Solver" in result.text
