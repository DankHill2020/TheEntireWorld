from types import SimpleNamespace
import array
import os

from tech_connector.ui.three_d_mesh_painter_widget import (
    DccTimelineCacheWorker,
    ThreeDMeshPainterViewport,
    TimelineFrameArchive,
)


def test_fast_snapshot_merge_shares_static_scene_buffers_and_replaces_only_delta_fields():
    faces = [[0, 1, 2]] * 100
    uvs = [[0.0, 0.0]] * 50
    material = {"name": "skin", "base_color": [0.4, 0.3, 0.2]}
    static_vertices = [[0.0, 0.0, 0.0]] * 50
    previous_object = {
        "native_id": "|rig|body",
        "name": "body",
        "material": material,
        "geometry": {
            "representation": "mesh",
            "vertex_count": 50,
            "vertices": static_vertices,
            "faces": faces,
            "uvs": uvs,
            "topology_included": True,
        },
    }
    previous = {
        "provider_id": "maya:7001",
        "objects": [previous_object],
        "cameras": [{"native_id": "persp"}],
    }
    packed = array.array("f", [1.0, 2.0, 3.0] * 50)
    delta = {
        "provider_id": "maya:7001",
        "objects": [
            {
                "native_id": "|rig|body",
                "world_matrix": list(range(16)),
                "geometry": {
                    "representation": "mesh",
                    "vertex_count": 50,
                    "vertices_f32": packed,
                    "topology_included": False,
                },
            }
        ],
        "isolation": {"target_native_ids": ["|rig|body"]},
    }
    owner = SimpleNamespace(_dcc_scene_snapshots={"maya:7001": previous})

    merged = ThreeDMeshPainterViewport._merged_fast_transform_snapshot(owner, "maya:7001", delta)
    geometry = merged["objects"][0]["geometry"]

    assert geometry["vertices_f32"] is packed
    assert geometry["faces"] is faces
    assert geometry["uvs"] is uvs
    assert merged["objects"][0]["material"] is material
    assert merged["cameras"] is previous["cameras"]
    assert previous_object["geometry"]["vertices"] is static_vertices


def test_timeline_archive_exposes_float_offsets_and_deletes_its_file():
    archive = TimelineFrameArchive.create(provider="maya:7001", frame_count=3, floats_per_frame=6)
    path = archive.path
    try:
        offset = archive.write_frame(1, array.array("f", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))

        assert offset == 6
        assert list(archive.float_view[offset : offset + 6]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        assert os.path.isfile(path)
    finally:
        archive.close(delete=True)
    assert not os.path.exists(path)


def test_timeline_worker_rebases_object_offsets_into_one_shared_archive():
    packed = array.array("f", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    snapshot = {
        "objects": [
            {
                "native_id": "first",
                "geometry": {"vertices_f32": packed, "vertex_float_offset": 0, "vertex_count": 1},
            },
            {
                "native_id": "second",
                "geometry": {"vertices_f32": packed, "vertex_float_offset": 3, "vertex_count": 1},
            },
        ]
    }
    worker = DccTimelineCacheWorker(
        provider="maya:7001",
        frame_start=1,
        frame_end=2,
        target_native_ids=["first", "second"],
    )
    try:
        archived = worker._archive_frame_snapshot(snapshot, frame=2, frame_count=2, slot=1)
        first = archived["objects"][0]["geometry"]
        second = archived["objects"][1]["geometry"]

        assert first["vertices_f32"] is worker._archive.float_view
        assert second["vertices_f32"] is worker._archive.float_view
        assert first["vertex_float_offset"] == 6
        assert second["vertex_float_offset"] == 9
        assert list(first["vertices_f32"][6:12]) == list(packed)
    finally:
        if worker._archive is not None:
            worker._archive.close(delete=True)


def test_clearing_timeline_cache_releases_mapped_buffers_from_retained_scene():
    archive = TimelineFrameArchive.create(provider="maya:7001", frame_count=1, floats_per_frame=3)
    path = archive.path
    archive.write_frame(0, array.array("f", [1.0, 2.0, 3.0]))
    geometry = {
        "vertices": [[0.0, 0.0, 0.0]],
        "vertices_f32": archive.float_view,
        "vertex_float_offset": 0,
        "vertex_encoding": "f32-memoryview",
        "timeline_archive_path": path,
    }
    snapshot = {
        "objects": [{"native_id": "body", "geometry": geometry}],
        "timeline_archive": archive,
        "timeline_archive_slot": 0,
    }

    class Owner:
        _strip_timeline_archive_buffers = ThreeDMeshPainterViewport._strip_timeline_archive_buffers
        _clear_dcc_timeline_snapshot_cache = ThreeDMeshPainterViewport._clear_dcc_timeline_snapshot_cache

    owner = Owner()
    owner._dcc_timeline_archives = {path: archive}
    owner._dcc_timeline_snapshot_cache = {("maya:7001", 1, "fingerprint"): snapshot}
    owner._dcc_timeline_snapshot_cache_order = [("maya:7001", 1, "fingerprint")]
    owner._dcc_scene_snapshots = {"maya:7001": snapshot}

    owner._clear_dcc_timeline_snapshot_cache()

    assert "vertices_f32" not in geometry
    assert geometry["vertices"] == [[0.0, 0.0, 0.0]]
    assert "timeline_archive" not in snapshot
    assert not owner._dcc_timeline_snapshot_cache
    assert not os.path.exists(path)
