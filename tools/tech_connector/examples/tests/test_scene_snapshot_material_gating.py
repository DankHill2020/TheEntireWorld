import unittest

from tech_connector.services.dcc.scene_snapshot_provider import (
    blender_scene_snapshot_code,
    houdini_scene_snapshot_code,
    motionbuilder_scene_snapshot_code,
    unreal_scene_snapshot_code,
)


class SceneSnapshotMaterialGatingTests(unittest.TestCase):
    def test_blender_fast_snapshot_disables_material_walk(self):
        source = blender_scene_snapshot_code(include_geometry=False, include_materials=False)

        self.assertIn("include_materials = False", source)
        self.assertIn("if not include_materials:", source)
        self.assertIn('"include_materials": include_materials', source)

    def test_unreal_fast_snapshot_disables_material_walk(self):
        source = unreal_scene_snapshot_code(include_materials=False)

        self.assertIn("include_materials = False", source)
        self.assertIn("if not include_materials:", source)
        self.assertIn('"include_materials": include_materials', source)

    def test_blender_snapshot_includes_session_viewport_metadata(self):
        source = blender_scene_snapshot_code(include_geometry=False, include_materials=False)

        self.assertIn('area.type == "VIEW_3D"', source)
        self.assertIn('"viewport_capture": _viewport_capture_payload()', source)
        self.assertIn('"aspect_ratio": float(camera_aspect_ratio)', source)
        self.assertIn('"process_id": int(os.getpid())', source)
        self.assertIn('"frame_start": float(bpy.context.scene.frame_start)', source)
        self.assertIn('"frame_end": float(bpy.context.scene.frame_end)', source)
        self.assertIn('"fps": float(render.fps)', source)

    def test_blender_material_snapshot_preserves_uv_and_pbr_inputs(self):
        source = blender_scene_snapshot_code(include_geometry=True, include_materials=True)

        self.assertIn('geometry["uvs"]', source)
        self.assertIn('geometry["face_uv_indices"]', source)
        self.assertIn('("Transmission Weight", "Transmission")', source)
        self.assertIn('"texture_paths": texture_paths', source)

    def test_blender_binary_snapshot_moves_geometry_serialization_off_main_thread(self):
        source = blender_scene_snapshot_code(
            include_geometry=True,
            include_materials=True,
            binary_path="C:/tmp/scene.bin",
        )

        compile(source, "<blender_binary_snapshot>", "exec")
        self.assertIn('mesh.transform(eval_obj.matrix_world)', source)
        self.assertIn('mesh.vertices.foreach_get("co", vertices)', source)
        self.assertIn('uv_layer.data.foreach_get("uv", uvs)', source)
        self.assertIn('binary_file.write(geometry_binary)', source)

    def test_other_native_snapshots_include_camera_gate_and_process_identity(self):
        for source in (
            motionbuilder_scene_snapshot_code(),
            houdini_scene_snapshot_code(include_geometry=False),
            unreal_scene_snapshot_code(include_materials=False),
        ):
            with self.subTest(source=source[:80]):
                self.assertIn('"aspect_ratio"', source)
                self.assertIn('"process_id": int(os.getpid())', source)


if __name__ == "__main__":
    unittest.main()
