from __future__ import annotations

from unreal_tools.sequence_publish_adapter import manifest_from_workspace, publish_sequence_workspace
from utilities.sequence_workspace import new_document, new_entry


def test_workspace_publish_manifest_preserves_identity_and_manual_skeleton() -> None:
    document = new_document(host="blender", export_directory="C:/Exports", fps=23.976)
    document["entries"] = [new_entry(
        "Hero_Run", 1001, 1048, entry_id="hero-run", namespace="Hero",
        skeleton="/Game/Hero/SK_Hero", nodes=["Hero"], export_directory="C:/Exports",
    )]
    manifest = manifest_from_workspace(
        document, destination_path="/Game/Hero/Animations", conflict_policy="version",
    )
    assert manifest["entries"][0]["id"] == "hero-run"
    assert manifest["entries"][0]["source_file"] == "C:/Exports/Hero_Run.fbx"
    assert manifest["entries"][0]["target_skeleton"] == "/Game/Hero/SK_Hero"
    assert manifest["conflict_policy"] == "version"
    assert manifest["entries"][0]["frame_rate_denominator"] == 1000


def test_workspace_manifest_fingerprints_existing_exports(tmp_path) -> None:
    source = tmp_path / "Hero_Run.fbx"
    source.write_bytes(b"stable-fbx")
    document = new_document(host="3dsmax", export_directory=str(tmp_path), fps=30)
    document["entries"] = [new_entry(
        "Hero_Run", 0, 30, namespace="Hero", skeleton="/Game/Hero/SK_Hero",
        export_directory=str(tmp_path),
    )]
    manifest = manifest_from_workspace(document)
    assert len(manifest["entries"][0]["source_hash"]) == 64


def test_publish_stops_after_blocked_unreal_preflight(monkeypatch, tmp_path) -> None:
    from unreal_tools import unreal_subprocess

    document = new_document(host="blender", export_directory=str(tmp_path), fps=24)
    document["entries"] = [new_entry(
        "Missing", 1, 10, namespace="Hero", skeleton="/Game/Hero/SK_Hero",
        export_directory=str(tmp_path),
    )]
    monkeypatch.setattr(unreal_subprocess, "run_preflight_sequence_import", lambda *_args, **_kwargs: {
        "can_import": False, "job_id": "blocked-job", "entries": [], "error_count": 1,
    })
    monkeypatch.setattr(
        unreal_subprocess, "run_import_gameplay_animations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("import must not run")),
    )
    result = publish_sequence_workspace(document)
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["job_id"] == "blocked-job"
