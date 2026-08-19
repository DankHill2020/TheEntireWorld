import array
import unittest

from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
from tech_connector.services.dcc.scene_delta_contract import (
    FRAME_DELTA_SCHEMA,
    frame_delta_has_gpu_points,
    normalize_frame_delta,
)


class SceneDeltaContractTests(unittest.TestCase):
    def test_blender_bulk_sampler_generates_valid_python_without_material_work(self):
        source = BlenderBridge().get_fast_timeline_sample_code(
            target_native_ids=["Cube"],
            binary_path="C:/tmp/blender_frame.f32",
            frame=12.5,
        )

        compile(source, "<blender-fast-sampler>", "exec")
        self.assertIn('mesh.vertices.foreach_get("co", packed)', source)
        self.assertIn('"include_materials": False', source)
        self.assertNotIn("active_material", source)

    def test_houdini_bulk_sampler_generates_valid_python_without_point_loops(self):
        source = HoudiniBridge().get_fast_timeline_sample_code(
            target_native_ids=["/obj/character/OUT"],
            binary_path="C:/tmp/houdini_frame.f32",
            frame=24.0,
        )

        compile(source, "<houdini-fast-sampler>", "exec")
        self.assertIn('geometry.pointFloatAttribValuesAsString("P")', source)
        self.assertIn('"include_materials": False', source)
        self.assertNotIn("for point in geometry.points()", source)

    def test_promotes_provider_packet_without_copying_packed_points(self):
        packed = array.array("f", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        source = {
            "schema": "tech_connector.maya.timeline_sample.v2",
            "provider_id": "maya",
            "objects": [
                {
                    "native_id": "|mesh",
                    "world_matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                    "geometry": {
                        "representation": "mesh",
                        "coordinate_space": "object",
                        "vertex_count": 2,
                        "vertices_f32": packed,
                    },
                }
            ],
        }

        packet = normalize_frame_delta(source)

        self.assertEqual(packet["schema"], FRAME_DELTA_SCHEMA)
        self.assertEqual(packet["source_schema"], source["schema"])
        self.assertIs(packet["objects"][0]["geometry"]["vertices_f32"], packed)
        self.assertEqual(packet["contract_errors"], [])
        self.assertTrue(frame_delta_has_gpu_points(packet))

    def test_rejects_truncated_object_space_buffer_without_matrix(self):
        packet = normalize_frame_delta(
            {
                "provider_id": "blender",
                "objects": [
                    {
                        "native_id": "Cube",
                        "geometry": {
                            "coordinate_space": "object",
                            "vertex_count": 2,
                            "vertices_f32": array.array("f", [0.0, 1.0, 2.0]),
                        },
                    }
                ],
            }
        )

        self.assertTrue(any("world_matrix" in error for error in packet["contract_errors"]))
        self.assertTrue(any("truncated" in error for error in packet["contract_errors"]))
        self.assertFalse(frame_delta_has_gpu_points(packet))


if __name__ == "__main__":
    unittest.main()
