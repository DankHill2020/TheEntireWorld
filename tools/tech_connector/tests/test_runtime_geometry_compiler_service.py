from __future__ import annotations

import json
from pathlib import Path
import threading
from time import perf_counter

import numpy as np
import pytest

from tech_connector.game_engine.runtime.runtime_geometry_compiler_service import (
    compile_point_runtime_proxy,
    compile_virtualized_hard_surface,
)


def _grid(size: int = 12):
    vertices = [(float(x), float(y), 0.0) for y in range(size + 1) for x in range(size + 1)]
    faces = []
    for y in range(size):
        for x in range(size):
            a = y * (size + 1) + x
            faces.append((a, a + 1, a + size + 2, a + size + 1))
    return vertices, faces


def _package(path: Path):
    package = np.load(path)
    manifest = json.loads(bytes(package["manifest"]).decode("utf-8"))
    return package, manifest


def test_point_proxy_preserves_pbr_material_and_exact_source_mapping(tmp_path: Path) -> None:
    vertices, faces = _grid(4)
    material_ids = [index % 2 for index in range(len(faces))]
    output = tmp_path / "grid.tcsurfels"

    result = compile_point_runtime_proxy(
        vertices,
        faces,
        output,
        face_material_ids=material_ids,
        materials=[
            {"base_color": [1.0, 0.0, 0.0, 1.0], "roughness": 0.2, "metallic": 0.0},
            {"base_color": [0.0, 0.0, 1.0, 1.0], "roughness": 0.8, "metallic": 1.0},
        ],
        page_size=32,
    )
    package, manifest = _package(output)

    assert result["surfel_count"] == len(faces) * 2
    assert manifest["schema"] == "tech_connector.point_runtime_proxy.v1"
    assert set(package["material_ids"]) == {0, 1}
    assert set(package["source_face_ids"]) == set(range(len(faces)))
    assert package["pbr"].shape == (len(faces) * 2, 9)
    assert np.allclose(np.linalg.norm(package["normals"], axis=1), 1.0)


def test_virtualized_mesh_respects_meshlet_limits_and_source_ids(tmp_path: Path) -> None:
    vertices, faces = _grid(12)
    output = tmp_path / "grid.tcvmesh"

    result = compile_virtualized_hard_surface(
        vertices,
        faces,
        output,
        max_vertices=32,
        max_triangles=24,
        meshlets_per_page=4,
    )
    package, manifest = _package(output)
    vertex_counts = np.diff(package["meshlet_vertex_offsets"])
    triangle_counts = np.diff(package["meshlet_triangle_offsets"])

    assert manifest["schema"] == "tech_connector.virtualized_hard_surface.v1"
    assert result["source_triangle_count"] == len(faces) * 2
    assert np.all(vertex_counts <= 32)
    assert np.all(triangle_counts <= 24)
    assert len(package["source_face_ids"]) == len(faces) * 2
    assert set(package["source_face_ids"]) == set(range(len(faces)))
    assert result["page_count"] == (result["meshlet_count"] + 3) // 4
    assert result["hierarchy"][-1]["level"] > 0


def test_runtime_geometry_compilers_reject_bad_geometry_and_cancel(tmp_path: Path) -> None:
    canceled = threading.Event()
    canceled.set()
    with pytest.raises(RuntimeError, match="canceled"):
        compile_virtualized_hard_surface(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            [(0, 1, 2)],
            tmp_path / "cancel.tcvmesh",
            cancel_event=canceled,
        )
    with pytest.raises(ValueError, match="degenerate"):
        compile_point_runtime_proxy(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
            [(0, 1, 2)],
            tmp_path / "bad.tcsurfels",
        )


def test_runtime_geometry_65k_triangle_performance_baseline(tmp_path: Path) -> None:
    vertices, faces = _grid(181)
    started = perf_counter()
    point = compile_point_runtime_proxy(vertices, faces, tmp_path / "baseline.tcsurfels")
    virtual = compile_virtualized_hard_surface(vertices, faces, tmp_path / "baseline.tcvmesh")
    elapsed = perf_counter() - started

    assert point["surfel_count"] >= 65_000
    assert virtual["source_triangle_count"] >= 65_000
    assert elapsed < 15.0
