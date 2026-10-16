from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace


class Skeleton:
    pass


class _EditorAssets:
    assets = {"/Game/Hero/SK_Hero": Skeleton()}
    existing = set()
    metadata = {}

    @classmethod
    def load_asset(cls, path):
        return cls.assets.get(str(path))

    @classmethod
    def does_asset_exist(cls, path):
        return str(path) in cls.existing

    @classmethod
    def get_metadata_tag(cls, asset, key):
        return cls.metadata.get((id(asset), str(key)), "")

    @classmethod
    def set_metadata_tag(cls, asset, key, value):
        cls.metadata[(id(asset), str(key))] = str(value)

    @classmethod
    def save_asset(cls, _path, **_kwargs):
        return True

    @classmethod
    def delete_asset(cls, path):
        cls.existing.discard(str(path))
        return True


class _Registry:
    def __init__(self, rows):
        self.rows = rows

    def get_assets_by_class(self, _asset_class):
        return list(self.rows)


def _load_importer(monkeypatch, rows=()):
    _EditorAssets.existing = set()
    _EditorAssets.metadata = {}
    fake_unreal = SimpleNamespace(
        Skeleton=Skeleton,
        EditorAssetLibrary=_EditorAssets,
        TopLevelAssetPath=lambda *parts: tuple(parts),
        AssetRegistryHelpers=SimpleNamespace(get_asset_registry=lambda: _Registry(rows)),
        log_error=lambda _message: None,
    )
    monkeypatch.setitem(__import__("sys").modules, "unreal", fake_unreal)
    module = importlib.import_module("unreal_tools.sequence_importer")
    monkeypatch.setattr(module, "unreal", fake_unreal)
    return module


def test_skeleton_resolver_accepts_full_paths_and_rejects_ambiguous_names(monkeypatch) -> None:
    rows = [
        SimpleNamespace(asset_name="SK_Hero", package_name="/Game/A/SK_Hero"),
        SimpleNamespace(asset_name="SK_Hero", package_name="/Game/B/SK_Hero"),
    ]
    importer = _load_importer(monkeypatch, rows)
    assert importer.resolve_skeleton_path("/Game/Hero/SK_Hero.SK_Hero") == "/Game/Hero/SK_Hero"
    try:
        importer.resolve_skeleton_path("SK_Hero")
    except ValueError as exc:
        assert "ambiguous" in str(exc)
        assert "/Game/A/SK_Hero" in str(exc)
    else:
        raise AssertionError("Expected an ambiguous short skeleton name to fail")


def test_gameplay_import_returns_honest_partial_result(monkeypatch, tmp_path: Path) -> None:
    rows = [SimpleNamespace(asset_name="SK_Hero", package_name="/Game/Hero/SK_Hero")]
    importer = _load_importer(monkeypatch, rows)
    manifest_path = tmp_path / "animations.json"
    manifest_path.write_text(json.dumps({
        "C:/Exports/Run.fbx": [1, 24, "Hero", "SK_Hero", "blue", ["Hero"]],
        "C:/Exports/Bad.fbx": [1, 24, "Bad", "Missing", "blue", ["Bad"]],
    }), encoding="utf-8")
    monkeypatch.setattr(
        importer, "import_animation",
        lambda _source, _skeleton, destination, name, **_kwargs: f"{destination}/{name}",
    )
    result = importer.import_gameplay_animations_from_json(str(manifest_path))
    assert result["status"] == "partial"
    assert result["ok"] is False
    assert result["imported"][0]["asset_path"] == "/Game/Animations/Run"
    assert result["failed"][0]["name"] == "Bad"


def test_command_fallback_uses_isolated_structured_result(monkeypatch, tmp_path: Path) -> None:
    from unreal_tools import unreal_subprocess

    executable = tmp_path / "UnrealEditor-Cmd.exe"
    project = tmp_path / "Demo.uproject"
    executable.write_text("", encoding="utf-8")
    project.write_text("{}", encoding="utf-8")
    observed = {}

    def fake_run(command, **kwargs):
        environment = kwargs["env"]
        observed["args_path"] = environment["TC_SEQUENCE_ARGS_PATH"]
        observed["result_path"] = environment["TC_SEQUENCE_RESULT_PATH"]
        with open(environment["TC_SEQUENCE_RESULT_PATH"], "w", encoding="utf-8") as stream:
            json.dump({"ok": True, "status": "succeeded"}, stream)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(unreal_subprocess.subprocess, "run", fake_run)
    result = unreal_subprocess._run_sequence_command(
        "gameplay_import_func.py", {"anim_dict_path": "C:/manifest.json"},
        str(project), str(executable),
    )
    assert result == {"ok": True, "status": "succeeded"}
    assert "tc_sequence_import_" in observed["args_path"]
    assert os.path.basename(observed["result_path"]) == "result.json"


def test_unreal_preflight_reports_unchanged_assets_without_writing(monkeypatch, tmp_path: Path) -> None:
    importer = _load_importer(monkeypatch)
    source = tmp_path / "Run.fbx"
    source.write_bytes(b"fbx-data")
    target = "/Game/Hero/Animations/Run"
    imported_asset = object()
    _EditorAssets.assets[target] = imported_asset
    _EditorAssets.existing.add(target)
    _EditorAssets.metadata[(id(imported_asset), "TechConnector.SourceHash")] = "same-hash"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "tech_connector.sequence_import.v2",
        "mode": "gameplay",
        "destination_path": "/Game/Hero/Animations",
        "entries": [{
            "id": "run", "name": "Run", "source_file": str(source),
            "source_hash": "same-hash", "target_skeleton": "/Game/Hero/SK_Hero",
        }],
    }), encoding="utf-8")
    report = importer.preflight_sequence_import_from_json(str(manifest))
    assert report["can_import"] is True
    assert report["error_count"] == 0
    assert report["entries"][0]["action"] == "skip_unchanged"
    assert report["entries"][0]["skeleton_path"] == "/Game/Hero/SK_Hero"


def test_source_control_checkout_failure_blocks_write(monkeypatch) -> None:
    importer = _load_importer(monkeypatch)

    class SourceControl:
        @classmethod
        def is_enabled(cls): return True
        @classmethod
        def is_available(cls): return True
        @classmethod
        def current_provider(cls): return "Perforce"
        @classmethod
        def check_out_file(cls, _path, silent=True): return False
        @classmethod
        def last_error_msg(cls): return "checked out by another user"

    importer.unreal.SourceControl = SourceControl
    try:
        importer._prepare_source_control_write("/Game/Run", exists=True, policy="auto")
    except RuntimeError as exc:
        assert "checked out by another user" in str(exc)
    else:
        raise AssertionError("A failed checkout must block an existing-asset update")


def test_cinematic_failure_reports_entry_and_retry_filters_to_failed_id(monkeypatch, tmp_path: Path) -> None:
    importer = _load_importer(monkeypatch)
    manifest_path = tmp_path / "cinematic.json"
    manifest_path.write_text(json.dumps({
        "schema": "tech_connector.sequence_import.v2",
        "mode": "cinematic",
        "destination_path": "/Game/Cinematics",
        "entries": [
            {"id": "camera", "kind": "camera", "name": "Camera", "shot": "Shot010",
             "source_file": "C:/Camera.fbx", "nodes": ["Camera_Main"]},
            {"id": "hero", "kind": "animation", "name": "Hero", "shot": "Shot010",
             "source_file": "C:/Hero.fbx", "namespace": "Hero", "target_skeleton": "/Game/Hero/SK_Hero"},
        ],
    }), encoding="utf-8")

    def fail_once(*_args, **_kwargs):
        raise importer.CinematicEntryImportError("hero", "Hero", RuntimeError("bad animation"), ["camera"])

    monkeypatch.setattr(importer, "create_cinematic_sequence", fail_once)
    first = importer.create_cinematic_sequence_from_json(str(manifest_path), from_cmd=False)
    assert first["status"] == "partial"
    assert first["updated"][0]["id"] == "camera"
    assert first["failed"][0]["id"] == "hero"

    captured = {}
    monkeypatch.setattr(
        importer, "create_cinematic_sequence",
        lambda payload, *_args, **_kwargs: captured.setdefault("payload", payload) or "/Game/Cinematics/Test",
    )
    retry = importer.retry_failed_cinematic_sequence_from_json(str(manifest_path), first)
    assert retry["status"] == "succeeded"
    assert [row["id"] for row in retry["updated"]] == ["hero"]
    assert [row["id"] for row in captured["payload"]["Shot010"]] == ["hero"]
