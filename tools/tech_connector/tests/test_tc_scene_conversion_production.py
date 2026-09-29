from __future__ import annotations

import json
import threading
import time

import pytest

from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene
from tech_connector.game_engine.scene.tc_scene_conversion_service import (
    EMBEDDED_SCENE_SNAPSHOT_BLOB,
    convert_to_tc,
)


def _snapshot(count: int) -> dict:
    return {
        "provider_id": "maya",
        "scene": "C:/show/launch_scene.ma",
        "unit_linear": "cm",
        "up_axis": "y",
        "frame_start": 1,
        "frame_end": 240,
        "frame_rate": 24.0,
        "objects": [
            {
                "native_id": f"|World|Mesh_{index}",
                "name": f"Mesh_{index}",
                "type": "mesh",
                "translation": [float(index), 0.0, 0.0],
                "bbox": [float(index), 0.0, 0.0, float(index) + 1.0, 1.0, 1.0],
                "geometry": {
                    "representation": "mesh",
                    "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                    "faces": [[0, 1, 2]],
                },
                "material": {"source_material_id": "DefaultMaterial", "shader_type": "standard_surface"},
            }
            for index in range(count)
        ],
    }


def test_large_scene_conversion_saves_and_reads_back_inside_budget(tmp_path) -> None:
    destination = tmp_path / "large_converted.tcscene"
    started = time.perf_counter()
    result = convert_to_tc(scene_snapshot=_snapshot(2_500), output_path=destination)
    document, blobs = load_federated_scene(destination)
    elapsed = time.perf_counter() - started

    assert result.report["status"] == "converted"
    assert result.report["counts"]["objects"] == 2_500
    assert result.report["counts"]["meshes"] == 2_500
    assert result.report["counts"]["materials"] == 2_500
    assert document.metadata["conversion_report"]["counts"] == result.report["counts"]
    assert blobs[EMBEDDED_SCENE_SNAPSHOT_BLOB] == result.blobs[EMBEDDED_SCENE_SNAPSHOT_BLOB]
    assert len(json.loads(blobs[EMBEDDED_SCENE_SNAPSHOT_BLOB])["objects"]) == 2_500
    assert elapsed < 5.0


def test_selection_conversion_is_scoped_and_stable() -> None:
    selected = _snapshot(3)
    first = convert_to_tc(scene_snapshot=selected, scope="selection", source_native_id="|World|Mesh_1")
    second = convert_to_tc(scene_snapshot=selected, scope="selection", source_native_id="|World|Mesh_1")

    assert first.report["scope"] == "selection"
    assert first.report["source_native_id"] == "|World|Mesh_1"
    assert [item["native_id"] for item in first.scene_snapshot["objects"]] == [
        item["native_id"] for item in second.scene_snapshot["objects"]
    ]
    assert all(item["source_ref"]["provider_id"] == "maya" for item in first.scene_snapshot["objects"])


def test_scene_conversion_rejects_empty_or_canceled_work_without_output(tmp_path) -> None:
    empty_destination = tmp_path / "empty.tcscene"
    with pytest.raises(ValueError, match="convertible objects"):
        convert_to_tc(scene_snapshot={"provider_id": "maya", "objects": []}, output_path=empty_destination)

    canceled_destination = tmp_path / "canceled.tcscene"
    canceled = threading.Event()
    canceled.set()
    with pytest.raises(RuntimeError, match="canceled"):
        convert_to_tc(scene_snapshot=_snapshot(1), output_path=canceled_destination, cancel_event=canceled)

    assert not empty_destination.exists()
    assert not canceled_destination.exists()
