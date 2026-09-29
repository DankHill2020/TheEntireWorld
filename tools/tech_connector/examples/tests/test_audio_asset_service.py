from __future__ import annotations

import json
import struct
import wave

from tech_connector.game_engine.assets.audio_asset_service import (
    AUDIO_RUNTIME_SCHEMA,
    audio_mixer_defaults,
    validate_audio_asset,
)
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI


def _write_wave(path, *, frames: int = 480) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48_000)
        output.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))


def test_imported_clip_settings_are_editable_without_modifying_source_media(tmp_path) -> None:
    source = tmp_path / "source.wav"; _write_wave(source); source_bytes = source.read_bytes()
    api = TCEditorAPI(tmp_path / "project")
    clip = api.import_asset(source, folder="Assets/Audio")
    settings = api.set_audio_clip_settings(clip.asset_id, {
        "load_mode": "stream", "compression": "opus", "quality": 0.65,
        "loop": True, "loop_start_seconds": 0.1, "loop_end_seconds": 1.0,
    })
    assert settings["load_mode"] == "stream"
    assert api.database.asset(clip.asset_id).source_path.read_bytes() == source_bytes
    artifact = api.cook_audio_asset(clip.asset_id, platform="windows", quality="high")
    payload = artifact.path.read_bytes()
    assert payload.startswith(b"TCAUDIO1")
    header_size = struct.unpack("<I", payload[8:12])[0]
    header = json.loads(payload[12:12 + header_size])
    assert header["schema"] == AUDIO_RUNTIME_SCHEMA
    assert header["settings"]["compression"] == "opus"


def test_sound_cue_tracks_clip_and_attenuation_dependencies_and_cooks(tmp_path) -> None:
    source = tmp_path / "impact.wav"; _write_wave(source)
    api = TCEditorAPI(tmp_path / "project")
    clip = api.import_asset(source, folder="Assets/Audio")
    attenuation = api.create_audio_attenuation("Impact3D")
    cue = api.create_sound_cue("Impact", properties={
        "attenuation_asset_id": attenuation.asset_id,
        "graph": {"nodes": [
            {"id": "wave", "type": "wave_player", "parameters": {"clip_asset_id": clip.asset_id}},
            {"id": "pitch", "type": "modulator", "parameters": {"pitch_min": 0.92, "pitch_max": 1.08}},
            {"id": "output", "type": "output", "parameters": {}},
        ], "connections": [{"source": "wave", "target": "pitch"}, {"source": "pitch", "target": "output"}]},
    })
    assert set(api.database.dependencies(cue.asset_id)) == {clip.asset_id, attenuation.asset_id}
    assert api.validate_audio_asset(cue.asset_id) == []
    runtime = json.loads(api.cook_audio_asset(cue.asset_id).path.read_text(encoding="utf-8"))
    assert [row["opcode"] for row in runtime["operations"]] == ["wave_player", "modulator", "output"]


def test_mixer_validation_detects_cycles_unknown_dsp_and_missing_master() -> None:
    mixer = audio_mixer_defaults()
    mixer["groups"] = [
        {"id": "a", "name": "A", "parent_id": "b", "effects": [{"type": "studio_secret"}]},
        {"id": "b", "name": "B", "parent_id": "a", "effects": []},
    ]
    codes = {item.code for item in validate_audio_asset("tc.audio_mixer", mixer)}
    assert {"missing_master", "mixer_cycle", "unknown_dsp"} <= codes


def test_python_api_creates_full_audio_family_and_manifest(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    mixer = api.create_audio_mixer("MainMix")
    attenuation = api.create_audio_attenuation("World3D")
    reverb = api.create_audio_reverb("Cavern", preset="cave")
    cue = api.create_sound_cue("Ambience")
    for receipt in (mixer, attenuation, reverb, cue):
        assert api.validate_audio_asset(receipt.asset_id) == []
        assert api.cook_audio_asset(receipt.asset_id).path.is_file()
    manifest = json.loads(api.cook([cue.asset_id]).artifact.path.read_text(encoding="utf-8"))
    assert manifest["assets"][0]["derived_outputs"][0]["kind"] == "sound_cue_runtime"
    assert "convert_unity_audio" in api.capability_contract()["audio_operations"]


def test_unreal_audio_conversion_maps_cue_attenuation_and_concurrency(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.convert_unreal_audio({
        "engine_version": "5.8",
        "attenuation_settings": [{"name": "ATTN_Weapon", "object_path": "/Game/Audio/ATTN_Weapon", "spatialize": True, "inner_radius": 2, "falloff_distance": 80}],
        "sound_cues": [{
            "name": "SC_Weapon", "object_path": "/Game/Audio/SC_Weapon", "attenuation": "/Game/Audio/ATTN_Weapon",
            "concurrency": {"maximum_voices": 8, "resolution": "stop_oldest"},
            "nodes": [{"id": "wave", "type": "SoundNodeWavePlayer", "parameters": {"clip_asset_id": "wave-id"}}, {"id": "out", "type": "Output"}],
            "connections": [{"source": "wave", "target": "out"}],
        }],
    })
    cue = api.audio.properties(receipt["source_to_asset"]["/Game/Audio/SC_Weapon"])
    assert cue["attenuation_asset_id"] == receipt["source_to_asset"]["/Game/Audio/ATTN_Weapon"]
    assert cue["concurrency"]["maximum_voices"] == 8
    assert cue["graph"]["nodes"][0]["type"] == "wave_player"


def test_unity_audio_conversion_creates_spatial_cue_and_attenuation(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.convert_unity_audio({
        "unity_version": "6000.0", "audio_sources": [{
            "name": "Footsteps", "guid": "source-guid", "clips": ["step-a", "step-b"],
            "volume": 0.8, "pitch": 1.0, "priority": 64, "spatialBlend": 1.0,
            "minDistance": 1.5, "maxDistance": 35.0, "dopplerLevel": 0.25, "spread": 15.0,
            "filters": [{"type": "AudioLowPassFilter", "cutoff": 8000}],
        }],
    })
    assert len(receipt["asset_ids"]) == 2
    cue = api.audio.properties(receipt["source_to_asset"]["source-guid"])
    attenuation_id = receipt["source_to_asset"]["source-guid:attenuation"]
    assert cue["attenuation_asset_id"] == attenuation_id
    assert cue["spatialization"]["enabled"] is True
    assert cue["graph"]["nodes"][2]["type"] == "random"
    attenuation = api.audio.properties(attenuation_id)
    assert attenuation["minimum_distance"] == 1.5
    assert attenuation["maximum_distance"] == 35.0

