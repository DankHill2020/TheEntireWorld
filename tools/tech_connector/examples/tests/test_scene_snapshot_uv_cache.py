from types import SimpleNamespace
import unittest

from tech_connector.ui.three_d_mesh_painter_widget import (
    FBXMeshModel,
    ThreeDMeshPainterViewport,
)


class SceneSnapshotUvCacheTests(unittest.TestCase):
    def test_source_textures_remain_lazy_until_material_display(self):
        snapshot = {
            "provider_id": "maya",
            "unit_linear": "cm",
            "up_axis": "y",
            "objects": [
                {
                    "native_id": "|mesh",
                    "name": "mesh",
                    "type": "mesh",
                    "visible": True,
                    "bbox": [0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
                    "material": {"texture_paths": {"base_color": "Z:/does/not/need/to/be/read.exr"}},
                    "geometry": {
                        "representation": "mesh",
                        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                        "faces": [[0, 1, 2]],
                    },
                }
            ],
        }

        model = FBXMeshModel.from_scene_snapshot(snapshot)

        self.assertEqual(model.source_texture_images, {})
        self.assertEqual(model.scene_proxy_objects[0].texture_bindings["base_color"], "Z:/does/not/need/to/be/read.exr")

    def test_uv_seams_reuse_one_source_point_in_fast_frames(self):
        snapshot = {
            "provider_id": "maya",
            "unit_linear": "cm",
            "up_axis": "y",
            "objects": [
                {
                    "native_id": "|mesh",
                    "name": "mesh",
                    "type": "mesh",
                    "visible": True,
                    "bbox": [0.0, 0.0, 0.0, 1.0, 1.0, 0.0],
                    "geometry": {
                        "representation": "mesh",
                        "vertices": [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [1.0, 1.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        "faces": [[0, 1, 2], [0, 2, 3]],
                        "uvs": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.25, 0.0]],
                        "face_uv_indices": [[0, 1, 2], [4, 2, 3]],
                    },
                }
            ],
        }
        model = FBXMeshModel.from_scene_snapshot(snapshot)
        proxy = model.scene_proxy_objects[0]

        self.assertTrue(proxy.mesh_data.has_uvs)
        self.assertEqual(proxy.mesh_data.source_vertex_count, 4)
        self.assertEqual(proxy.mesh_data.vertex_count, 5)
        seam_offsets = [
            offset
            for offset, source_index in enumerate(proxy.mesh_data.source_vertex_indices)
            if source_index == 0
        ]
        self.assertEqual(len(seam_offsets), 2)

        fast_snapshot = {
            "provider_id": "maya",
            "unit_linear": "cm",
            "up_axis": "y",
            "objects": [
                {
                    "native_id": "|mesh",
                    "bbox": [2.0, 0.0, 0.0, 3.0, 1.0, 0.0],
                    "geometry": {
                        "representation": "mesh",
                        "vertices": [
                            [2.0, 0.0, 0.0],
                            [3.0, 0.0, 0.0],
                            [3.0, 1.0, 0.0],
                            [2.0, 1.0, 0.0],
                        ],
                    },
                }
            ],
        }
        owner = SimpleNamespace(mesh=model, _last_geometry_apply_ms=0.0)
        changed = ThreeDMeshPainterViewport._apply_fast_transform_snapshot_updates(
            owner,
            {"maya": fast_snapshot},
        )

        self.assertTrue(changed)
        seam_positions = {
            (
                model.vertices[proxy.mesh_data.vertex_start + offset].x,
                model.vertices[proxy.mesh_data.vertex_start + offset].y,
                model.vertices[proxy.mesh_data.vertex_start + offset].z,
            )
            for offset in seam_offsets
        }
        self.assertEqual(len(seam_positions), 1)


if __name__ == "__main__":
    unittest.main()
