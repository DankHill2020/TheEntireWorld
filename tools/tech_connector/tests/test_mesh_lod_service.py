from __future__ import annotations

from pathlib import Path
import threading

import pytest

from tech_connector.game_engine.runtime.mesh_lod_service import (
    MeshLodLevel,
    MeshLodRequest,
    generate_mesh_lods,
)
from tech_connector.game_engine.scene.native_fbx_service import find_blender_executable


def _write_grid_obj(path: Path, size: int = 8) -> Path:
    lines = []
    for y in range(size + 1):
        for x in range(size + 1):
            lines.append(f"v {x} {y} 0")
            lines.append(f"vt {x / size} {y / size}")
    for y in range(size):
        for x in range(size):
            a = y * (size + 1) + x + 1
            b = a + 1
            d = (y + 1) * (size + 1) + x + 1
            c = d + 1
            lines.append(f"f {a}/{a} {b}/{b} {c}/{c} {d}/{d}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def test_lod_contract_rejects_missing_sources_and_bad_level_order(tmp_path: Path) -> None:
    request = MeshLodRequest(
        str(tmp_path / "missing.obj"),
        str(tmp_path / "out"),
        levels=(MeshLodLevel("LOD1", 0.25), MeshLodLevel("LOD0", 1.0)),
    )

    errors = request.validate()

    assert any("missing" in error for error in errors)
    assert any("ordered" in error for error in errors)


def test_pre_canceled_lod_generation_does_not_launch(tmp_path: Path) -> None:
    source = _write_grid_obj(tmp_path / "grid.obj")
    canceled = threading.Event()
    canceled.set()

    with pytest.raises(RuntimeError, match="canceled"):
        generate_mesh_lods(MeshLodRequest(str(source), str(tmp_path / "out")), cancel_event=canceled)


def test_live_blender_backend_generates_valid_glb_lod_chain(tmp_path: Path) -> None:
    if find_blender_executable() is None:
        pytest.skip("Blender is not installed.")
    source = _write_grid_obj(tmp_path / "grid.obj")
    request = MeshLodRequest(
        str(source),
        str(tmp_path / "lods"),
        levels=(MeshLodLevel("LOD0", 1.0), MeshLodLevel("LOD1", 0.5), MeshLodLevel("LOD2", 0.2)),
    )

    result = generate_mesh_lods(request, timeout=120.0)

    assert result["backend"] == "blender_decimate_glb"
    assert len(result["levels"]) == 3
    triangle_counts = [level["output_triangles"] for level in result["levels"]]
    assert triangle_counts[0] == 128
    assert triangle_counts[0] > triangle_counts[1] > triangle_counts[2]
    assert all(Path(level["output_path"]).is_file() for level in result["levels"])
    assert all(level["objects_after"][0]["uv_layers"] == 1 for level in result["levels"])
    assert not any(level["diagnostics"] for level in result["levels"])
    assert result["elapsed_ms"] < 30_000.0
