from __future__ import annotations

from pathlib import Path
import threading

import pytest

from tech_connector.game_engine.assets import CharacterMeshLodLevel, CharacterMeshLodRequest, generate_character_mesh_lods


def _obj(path: Path) -> Path:
    path.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n", encoding="ascii")
    return path


def test_character_lod_request_accepts_generated_and_custom_levels(tmp_path) -> None:
    source = _obj(tmp_path / "source.obj"); custom = _obj(tmp_path / "custom.obj")
    request = CharacterMeshLodRequest(str(source), str(tmp_path / "out"), levels=(
        CharacterMeshLodLevel("LOD0", 1.0), CharacterMeshLodLevel("LOD1", 0.5, source_path=str(custom)),
    ))
    assert request.validate() == []
    assert request.to_dict()["preserve_skinning"] is True
    assert request.to_dict()["levels"][1]["source_path"] == str(custom)


def test_character_lod_request_rejects_missing_custom_source(tmp_path) -> None:
    source = _obj(tmp_path / "source.obj")
    request = CharacterMeshLodRequest(str(source), str(tmp_path / "out"), levels=(
        CharacterMeshLodLevel("LOD0", 1.0), CharacterMeshLodLevel("LOD1", 0.5, source_path=str(tmp_path / "missing.fbx")),
    ))
    assert any("Custom LOD source is missing" in item for item in request.validate())


def test_pre_canceled_character_lod_generation_does_not_launch(tmp_path) -> None:
    source = _obj(tmp_path / "source.obj"); event = threading.Event(); event.set()
    with pytest.raises(RuntimeError, match="canceled"):
        generate_character_mesh_lods(CharacterMeshLodRequest(str(source), str(tmp_path / "out")), cancel_event=event)
