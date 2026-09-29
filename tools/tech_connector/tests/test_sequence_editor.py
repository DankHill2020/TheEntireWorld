from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService, builtin_asset_type_registry
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.sequence_asset_service import (
    TRACK_DEFINITIONS, TRACK_TYPES, SequenceAssetService, add_channel_key,
    build_render_jobs, evaluate_channel, evaluate_sequence, native_to_unity_timeline,
    native_to_unreal_level_sequence, new_binding, new_section, new_track,
    new_level_blend_section, sequence_defaults, track_preset, unity_timeline_to_native,
    validate_sequence,
)
from tech_connector.game_engine.runtime.level_sequence_runtime_service import LevelSequenceRuntimeDirector
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor, editor_pages_for_asset
from tech_connector.ui.game_engine.sequence_editor import (
    SequenceBindingsEditorWidget, SequenceCurveEditorWidget, SequenceEditorWidget,
    SequenceRenderExportWidget,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_level_sequence_is_first_class_creatable_asset() -> None:
    descriptor = builtin_asset_type_registry().require("tc.level_sequence")
    assert descriptor.display_name == "Level Sequence"
    assert descriptor.editor_id == "sequence"
    assert descriptor.python_api_namespace == "editor.sequence"
    assert editor_pages_for_asset("tc.level_sequence")[0] == "Sequence"


def test_track_catalog_covers_full_cinematic_authoring() -> None:
    required = {"animation", "translation", "transform", "camera", "camera_cut", "sub_sequence", "bone_transform", "attachment", "constraint", "control_rig", "audio", "event", "property", "component_property", "visibility", "material", "effect", "spawn", "level_blend"}
    assert required.issubset(TRACK_TYPES)
    assert TRACK_DEFINITIONS["animation"]["asset_types"] == ("tc.animation_clip",)
    assert TRACK_DEFINITIONS["sub_sequence"]["asset_types"] == ("tc.level_sequence",)
    assert [channel["name"] for channel in track_preset("translation")["default_channels"]] == ["translation.x", "translation.y", "translation.z"]
    assert len(track_preset("transform")["default_channels"]) == 9
    assert [channel["name"] for channel in track_preset("camera")["default_channels"]] == ["focal_length", "aperture", "focus_distance"]


def test_bone_component_bindings_and_channel_evaluation() -> None:
    values = sequence_defaults(duration_frames=60)
    actor = new_binding("Hero", object_id="level.hero")
    mesh = new_binding("Hero Mesh", binding_type="component", parent_binding_id=actor["id"], component_path="SkeletalMeshComponent")
    hand = new_binding("Right Hand", binding_type="bone", parent_binding_id=mesh["id"], skeleton_asset_id="tc.asset.hero_skeleton", bone_name="hand_r", socket_name="weapon_socket")
    values["bindings"].extend([actor, mesh, hand])
    track = track_preset("bone_transform", "Hand Motion", binding_id=hand["id"])
    section = new_section("Aim", 0, 60)
    add_channel_key(section, "translation.x", 0, 0.0)
    add_channel_key(section, "translation.x", 30, 12.0)
    track["sections"].append(section); values["tracks"].append(track)
    assert not [issue for issue in validate_sequence(values) if issue.severity == "error"]
    result = evaluate_sequence(values, 15)["active_sections"][0]
    assert result["binding"]["bone_name"] == "hand_r"
    assert result["binding"]["component_path"] == ""
    assert result["evaluated_channels"]["translation.x"] == 6.0
    assert evaluate_channel(section["channels"][0], 30) == 12.0


def test_sequence_authoring_validation_evaluation_and_cook(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = SequenceAssetService(tmp_path, database)
    receipt = service.create("Opening", duration_frames=240, fps=24)
    values = service.properties(receipt.asset_id)

    camera = new_binding("Hero Camera", object_id="level.camera.hero")
    values["bindings"].append(camera)
    cuts = new_track("camera_cut", "Camera Cuts", binding_id=camera["id"])
    cut = new_section("Establishing", 0, 96)
    cuts["sections"].append(cut)
    events = new_track("event", "Gameplay Events")
    event_section = new_section("Intro Events", 0, 120)
    event_section["channels"] = [{"name": "Events", "keys": [{"frame": 48, "event": "DoorOpen", "payload": {"door": "A"}}]}]
    events["sections"].append(event_section)
    values["tracks"].extend([cuts, events])
    service.update(receipt.asset_id, values)

    assert not [issue for issue in service.validate(receipt.asset_id) if issue.severity == "error"]
    evaluated = evaluate_sequence(values, 48)
    assert evaluated["camera_cut"]["name"] == "Establishing"
    assert evaluated["events"][0]["event"] == "DoorOpen"
    artifact = service.cook(receipt.asset_id, platform="windows", quality="high")
    assert artifact.path.suffix == ".tcseqbin"
    assert artifact.path.is_file()


def test_sequence_interchange_is_bidirectional() -> None:
    values = sequence_defaults(duration_frames=90, fps=30)
    track = new_track("audio", "Score")
    track["sections"].append(new_section("Theme", 15, 75, asset_id="tc.asset.score"))
    values["tracks"].append(track)

    unreal = native_to_unreal_level_sequence(values)
    assert unreal["playback_end"] == 90
    assert unreal["tracks"][0]["type"] == "audio"

    unity = native_to_unity_timeline(values)
    assert unity["tracks"][0]["type"] == "AudioTrack"
    assert unity["tracks"][0]["clips"][0]["start"] == 0.5
    restored = unity_timeline_to_native(unity)
    assert restored["tracks"][0]["type"] == "audio"
    assert restored["tracks"][0]["sections"][0]["start_frame"] == 15


def test_render_jobs_follow_camera_cuts_and_safe_settings() -> None:
    values = sequence_defaults(duration_frames=120, fps=24)
    cuts = new_track("camera_cut", "Camera Cuts")
    cuts["sections"] = [
        new_section("Shot 010", 0, 48, asset_id="camera_a"),
        new_section("Shot 020", 48, 120, asset_id="camera_b"),
    ]
    values["tracks"].append(cuts)
    values["render_settings"]["frame_handles"] = 2
    jobs = build_render_jobs(values)
    assert [(job["name"], job["start_frame"], job["end_frame"]) for job in jobs] == [
        ("Shot 010", -2, 50), ("Shot 020", 46, 122),
    ]
    assert jobs[1]["camera_binding_id"] == "camera_b"


def test_sequence_blends_real_levels_and_emits_runtime_streaming_commands(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(tmp_path, database)
    reality_a = operations.create_asset("tc.level", "RealityA", folder="Assets/Levels")
    reality_b = operations.create_asset("tc.level", "RealityB", folder="Assets/Levels")
    sequences = SequenceAssetService(tmp_path, database)
    sequence = sequences.create("RealityShift", duration_frames=120, fps=30)
    values = sequences.properties(sequence.asset_id)
    track = track_preset("level_blend", "Reality Blend")
    first = new_level_blend_section("Reality A", reality_a.asset_id, 0, 70, ease_in=20, ease_out=20)
    second = new_level_blend_section("Reality B", reality_b.asset_id, 50, 120, ease_in=20, ease_out=20)
    track["sections"].extend([first, second]); values["tracks"].append(track); sequences.update(sequence.asset_id, values)

    at_overlap = evaluate_sequence(values, 60)["level_blends"]
    assert {item["level_asset_id"] for item in at_overlap} == {reality_a.asset_id, reality_b.asset_id}
    assert {item["weight"] for item in at_overlap} == {0.5}

    received = []
    director = LevelSequenceRuntimeDirector(tmp_path, database, command_sink=received.append)
    preload = director.tick(sequence.asset_id, -10)
    assert preload.commands[0].operation == "preload_level"
    frame = director.tick(sequence.asset_id, 60)
    assert len([command for command in frame.commands if command.operation == "set_level_blend"]) == 2
    assert all(command.payload["preserve_player_state"] for command in frame.commands if command.operation == "set_level_blend")


def test_sequence_validation_catches_authoring_errors() -> None:
    values = sequence_defaults()
    values["tracks"] = [{"id": "", "type": "unknown", "binding_id": "missing", "sections": []}]
    codes = {issue.code for issue in validate_sequence(values)}
    assert {"invalid_tracks", "unknown_track_type", "missing_binding"}.issubset(codes)


def test_sequence_editor_round_trips_tracks_sections_and_transport() -> None:
    widget = SequenceEditorWidget()
    widget.load_settings(sequence_defaults(duration_frames=180, fps=30))
    binding_id = widget.add_binding("Player", "level.player")
    track_id = widget.add_track("animation", "Player Animation", binding_id)
    section_id = widget.add_section("Run", 10, 70, "tc.asset.run")
    values = widget.settings()
    assert values["bindings"][0]["id"] == binding_id
    assert values["tracks"][0]["id"] == track_id
    assert values["tracks"][0]["sections"][0]["id"] == section_id
    assert values["tracks"][0]["sections"][0]["asset_id"] == "tc.asset.run"
    assert not widget.validation_issues()
    widget._section_edited(track_id, section_id, 20, 80)
    assert widget.settings()["tracks"][0]["sections"][0]["start_frame"] == 20

    restored = SequenceEditorWidget()
    restored.load_settings(values)
    assert restored.settings()["tracks"] == values["tracks"]


def test_sequence_curve_binding_and_render_pages_patch_one_document() -> None:
    values = sequence_defaults(duration_frames=100, fps=25)
    binding = new_binding("Camera", object_id="camera.main")
    track = new_track("transform", "Camera Transform", binding_id=binding["id"])
    section = new_section("Camera Move", 0, 100)
    track["sections"].append(section); values["bindings"].append(binding); values["tracks"].append(track)

    curves = SequenceCurveEditorWidget(); curves.load_settings(values); curves.add_key(25, 12.5, "bezier"); curves.apply_to(values)
    keys = values["tracks"][0]["sections"][0]["channels"][0]["keys"]
    assert keys == [{"frame": 25.0, "value": 12.5, "interpolation": "bezier"}]

    bindings = SequenceBindingsEditorWidget(); bindings.load_settings(values); bindings.add_binding("spawnable")
    assert len(bindings.bindings()) == 2

    render = SequenceRenderExportWidget(); render.load_settings(values); render.width.setValue(3840); render.height.setValue(2160); render.format.setCurrentText("exr")
    assert render.render_settings()["resolution"] == [3840, 2160]
    assert render.jobs.rowCount() == 1
    assert not render.validation_issues()


def test_python_api_exposes_sequence_authoring_and_editor_opens(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_level_sequence("GameplayIntro", duration_frames=150, fps=30)
    assert api.database.asset(receipt.asset_id).asset_type == "tc.level_sequence"
    assert api.sequence_track("camera_cut", "Cuts")["type"] == "camera_cut"
    assert api.get_level_sequence(receipt.asset_id)["playback_range"]["end"] == 150
    assert api.evaluate_level_sequence(receipt.asset_id, 12)["frame"] == 12
    assert api.level_sequence_render_jobs(receipt.asset_id)[0]["end_frame"] == 150
    assert api.cook_level_sequence(receipt.asset_id).path.suffix == ".tcseqbin"
    binding = api.add_sequence_binding(receipt.asset_id, "Hero", object_id="level.hero")
    track = api.add_sequence_track(receipt.asset_id, "translation", "Hero Translation", binding_id=binding["id"])
    section = api.add_sequence_section(receipt.asset_id, track["id"], "Move", 0, 60)
    api.add_sequence_key(receipt.asset_id, track["id"], section["id"], "translation.x", 0, 0.0)
    api.add_sequence_key(receipt.asset_id, track["id"], section["id"], "translation.x", 30, 10.0)
    assert api.evaluate_level_sequence(receipt.asset_id, 15)["active_sections"][0]["evaluated_channels"]["translation.x"] == 5.0

    editor = DedicatedAssetEditor(tmp_path, api.database)
    assert editor.open_asset(receipt.asset_id)
    assert any(isinstance(widget, SequenceEditorWidget) for _key, widget in editor._specialized_widgets)
    assert any(isinstance(widget, SequenceCurveEditorWidget) for _key, widget in editor._specialized_widgets)
    assert any(isinstance(widget, SequenceBindingsEditorWidget) for _key, widget in editor._specialized_widgets)
    assert any(isinstance(widget, SequenceRenderExportWidget) for _key, widget in editor._specialized_widgets)
