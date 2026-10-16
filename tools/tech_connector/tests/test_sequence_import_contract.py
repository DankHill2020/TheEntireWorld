from __future__ import annotations

from unreal_tools.sequence_import_contract import (
    SEQUENCE_IMPORT_SCHEMA, cinematic_payload_from_manifest, finish_import_result,
    new_import_result, normalize_sequence_manifest, validate_sequence_manifest,
)


def test_legacy_gameplay_manifest_is_upgraded_with_stable_entry_fields() -> None:
    manifest = normalize_sequence_manifest({
        "C:/Exports/Hero_Run.fbx": [1, 48, "Hero", "/Game/Hero/SK_Hero", "blue", ["Hero"]],
    })
    assert manifest["schema"] == SEQUENCE_IMPORT_SCHEMA
    assert manifest["mode"] == "gameplay"
    assert manifest["entries"][0]["name"] == "Hero_Run"
    assert manifest["entries"][0]["target_skeleton"] == "/Game/Hero/SK_Hero"
    assert manifest["entries"][0]["nodes"] == ["Hero"]
    assert validate_sequence_manifest(manifest) == ()


def test_v2_manifest_applies_job_destination_and_conflict_policy() -> None:
    manifest = normalize_sequence_manifest({
        "schema": SEQUENCE_IMPORT_SCHEMA,
        "job_id": "job-7",
        "mode": "gameplay",
        "destination_path": "/Game/Characters/Hero/Animations",
        "conflict_policy": "version",
        "entries": [{
            "id": "run", "name": "Run", "source_file": "C:/Exports/Run.fbx",
            "target_skeleton": "/Game/Hero/SK_Hero", "nodes": "Hero, Hero_Mesh",
        }],
    })
    assert manifest["entries"][0]["destination_path"] == "/Game/Characters/Hero/Animations"
    assert manifest["entries"][0]["nodes"] == ["Hero", "Hero_Mesh"]
    assert manifest["conflict_policy"] == "version"


def test_manifest_validation_rejects_duplicate_outputs_and_missing_targets() -> None:
    manifest = normalize_sequence_manifest({
        "schema": SEQUENCE_IMPORT_SCHEMA,
        "entries": [
            {"id": "a", "source_file": "C:/A.fbx", "name": "Run", "target_skeleton": ""},
            {"id": "b", "source_file": "C:/B.fbx", "name": "Run", "target_skeleton": "/Game/SK"},
        ],
    })
    codes = {issue["code"] for issue in validate_sequence_manifest(manifest)}
    assert codes == {"missing_target_skeleton", "duplicate_output"}


def test_structured_result_distinguishes_partial_failure() -> None:
    manifest = normalize_sequence_manifest({
        "C:/Exports/A.fbx": [1, 10, "Hero", "/Game/SK", "blue", ["Hero"]],
    })
    result = new_import_result(manifest)
    result["imported"].append({"id": "a", "asset_path": "/Game/A"})
    result["failed"].append({"id": "b", "error": "missing skeleton"})
    final = finish_import_result(result)
    assert final["ok"] is False
    assert final["status"] == "partial"


def test_cinematic_manifest_converts_to_existing_assembly_shape() -> None:
    manifest = normalize_sequence_manifest({
        "schema": SEQUENCE_IMPORT_SCHEMA,
        "mode": "cinematic",
        "destination_path": "/Game/Cinematics",
        "entries": [{
            "id": "camera", "kind": "camera", "source_file": "C:/Shot010_Camera.fbx",
            "name": "Camera", "namespace": "CAM", "shot": "Shot010", "nodes": ["Camera_Main"],
            "start_frame": 1001, "end_frame": 1048, "frame_rate_numerator": 24000,
            "frame_rate_denominator": 1001,
        }],
    }, mode="cinematic", destination_path="/Game/Cinematics")
    payload = cinematic_payload_from_manifest(manifest)
    assert payload["Shot010"][0]["name_space"] == "CAM"
    assert payload["Shot010"][0]["nodes"] == ["Camera_Main"]
    assert round(payload["Shot010"][0]["fps"], 3) == 23.976
