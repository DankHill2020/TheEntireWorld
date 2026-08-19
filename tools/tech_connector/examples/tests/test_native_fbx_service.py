import unittest
from unittest.mock import patch
import array
import json
from pathlib import Path
import subprocess
import tempfile
import threading

import numpy as np

from tech_connector.services.dcc.gpu_skinning_contract import (
    GpuSkinMeshSpec,
    build_skin_matrix_palette,
    emulate_sparse_gpu_skin_positions,
    sparse_render_influence_texels,
)
from tech_connector.services.dcc.native_fbx_service import (
    NativeFbxAsset,
    apply_native_joint_matrix_override,
    build_native_fbx_deformation_pose,
    find_blender_executable,
    import_native_fbx,
    import_native_scene,
    native_scene_import_capabilities,
)


class NativeFbxServiceTests(unittest.TestCase):
    def test_scene_import_capabilities_are_truthful_about_backend_availability(self):
        with patch(
            "tech_connector.game_engine.scene.native_fbx_service.find_blender_executable",
            return_value=None,
        ), patch(
            "tech_connector.game_engine.scene.native_fbx_service.find_blender_fbx_extractor",
            return_value=None,
        ):
            unavailable = native_scene_import_capabilities()
        self.assertFalse(unavailable["available"])
        self.assertFalse(unavailable["formats"][".gltf"]["available"])
        self.assertEqual(unavailable["implementation"], "external_converter")
        self.assertFalse(unavailable["in_process"])
        self.assertTrue(unavailable["dependency"]["required"])

        with tempfile.TemporaryDirectory() as directory:
            blender = Path(directory) / "blender.exe"
            worker = Path(directory) / "extract.py"
            blender.write_bytes(b"exe")
            worker.write_text("", encoding="utf-8")
            with patch(
                "tech_connector.game_engine.scene.native_fbx_service.find_blender_executable",
                return_value=blender,
            ), patch(
                "tech_connector.game_engine.scene.native_fbx_service.find_blender_fbx_extractor",
                return_value=worker,
            ):
                available = native_scene_import_capabilities()
        self.assertTrue(available["available"])
        self.assertTrue(available["formats"][".usd"]["geometry"])
        self.assertTrue(available["formats"][".glb"]["skinning"])
        self.assertFalse(available["formats"][".stl"]["animation"])

    def test_generic_scene_import_dispatches_supported_format_and_accepts_scene_schema(self):
        class CompleteProcess:
            returncode = 0

            def communicate(self, timeout=None):
                return "ok", ""

            def poll(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene.gltf"
            blender = Path(directory) / "blender.exe"
            worker = Path(directory) / "extract.py"
            source.write_text("{}", encoding="utf-8")
            blender.write_bytes(b"exe")
            worker.write_text("", encoding="utf-8")

            def launch(command, **_kwargs):
                manifest = Path(command[command.index("--manifest") + 1])
                floats = Path(command[command.index("--floats") + 1])
                uints = Path(command[command.index("--uints") + 1])
                manifest.write_text(json.dumps({
                    "schema": "tech_connector.native_scene_asset.v1",
                    "meshes": [],
                    "armatures": [],
                    "actions": [],
                }), encoding="utf-8")
                floats.write_bytes(b"")
                uints.write_bytes(b"")
                return CompleteProcess()

            with patch(
                "tech_connector.game_engine.scene.native_fbx_service.find_blender_fbx_extractor",
                return_value=worker,
            ), patch(
                "tech_connector.game_engine.scene.native_fbx_service.subprocess.Popen",
                side_effect=launch,
            ) as popen:
                asset = import_native_scene(source, blender_executable=blender)

        self.assertEqual(asset.source_format, "gltf")
        command = popen.call_args.args[0]
        self.assertIn(str(source.resolve()), command)

    def test_generic_scene_import_rejects_unknown_extension_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene.ma"
            source.write_text("", encoding="utf-8")
            with patch("tech_connector.game_engine.scene.native_fbx_service.subprocess.Popen") as popen:
                with self.assertRaisesRegex(ValueError, "supported scene file"):
                    import_native_scene(source)
        popen.assert_not_called()

    def test_missing_configured_backend_returns_none(self):
        with patch.dict("os.environ", {"TECH_CONNECTOR_BLENDER": "Z:/missing/blender.exe"}, clear=True):
            with patch("tech_connector.services.dcc.native_fbx_service.shutil.which", return_value=None):
                with patch("tech_connector.services.dcc.native_fbx_service.Path.is_dir", return_value=False):
                    self.assertIsNone(find_blender_executable())

    def test_pre_canceled_import_does_not_start_blender(self):
        canceled = threading.Event()
        canceled.set()
        with patch("tech_connector.game_engine.scene.native_fbx_service.subprocess.Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "canceled"):
                import_native_fbx("missing.fbx", cancel_event=canceled)
        popen.assert_not_called()

    def test_inflight_import_cancellation_terminates_blender(self):
        canceled = threading.Event()

        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.terminated = False

            def communicate(self, timeout=None):
                canceled.set()
                raise subprocess.TimeoutExpired("blender", timeout)

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scene.fbx"
            blender = Path(directory) / "blender.exe"
            worker = Path(directory) / "extract.py"
            source.write_bytes(b"fbx")
            blender.write_bytes(b"exe")
            worker.write_text("", encoding="utf-8")
            with patch(
                "tech_connector.game_engine.scene.native_fbx_service.find_blender_fbx_extractor",
                return_value=worker,
            ), patch(
                "tech_connector.game_engine.scene.native_fbx_service.subprocess.Popen",
                return_value=fake,
            ):
                with self.assertRaisesRegex(RuntimeError, "canceled"):
                    import_native_fbx(
                        source,
                        blender_executable=blender,
                        cancel_event=canceled,
                    )
        self.assertTrue(fake.terminated)

    def test_native_skin_binding_preserves_rest_pose_and_applies_local_joint_edits(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        armature_world = identity[:]
        armature_world[3] = 2.0
        child_local = identity[:]
        child_local[3] = 1.0
        root_frame_one = identity[:]
        root_frame_one[3] = 2.0
        child_frame_one = identity[:]
        child_frame_one[3] = 3.0
        root_frame_two = identity[:]
        root_frame_two[3] = 2.0
        child_frame_two = identity[:]
        child_frame_two[3] = 4.0
        floats = array.array("f", [
            0, 0, 0,
            1, 0, 0,
            2, 0, 0,
            1, 1, 1,
            *root_frame_one,
            *child_frame_one,
            *root_frame_two,
            *child_frame_two,
        ])
        integers = array.array("I", [0, 1, 2, 3, 0, 1, 1])
        asset = NativeFbxAsset(
            "synthetic.fbx",
            {
                "unit_scale": 1.0,
                "frame_start": 1,
                "frame_end": 2,
                "armatures": [{
                    "native_id": "Rig",
                    "world_matrix": armature_world,
                    "bones": [
                        {"name": "Root", "parent": "", "matrix_local": identity},
                        {"name": "Child", "parent": "Root", "matrix_local": child_local},
                    ],
                    "constraints": [],
                    "pose_cache": {
                        "available": True,
                        "frame_start": 1,
                        "frame_end": 2,
                        "frame_count": 2,
                        "joint_count": 2,
                        "matrix_float_offset": 12,
                    },
                }],
                "meshes": [{
                    "native_id": "Body",
                    "name": "Body",
                    "world_matrix": identity,
                    "armature_id": "Rig",
                    "vertex_count": 3,
                    "position_float_offset": 0,
                    "influence_offset_offset": 0,
                    "joint_index_offset": 4,
                    "weight_float_offset": 9,
                    "influence_count": 3,
                    "max_influences_per_vertex": 1,
                }],
                "actions": [],
            },
            floats,
            integers,
        )
        graph, _blobs = asset.to_editable_rig_graph()
        binding = asset.build_deformation_binding(graph)
        root_id = "native_fbx::Rig::Root"
        child_id = "native_fbx::Rig::Child"

        evaluated = graph.evaluate_local()
        self.assertEqual(evaluated.world_matrices[root_id][12:15], [200.0, 0.0, 0.0])
        self.assertEqual(evaluated.local_matrices[child_id][12:15], [100.0, 0.0, 0.0])
        mesh = binding["meshes"][0]
        spec = GpuSkinMeshSpec("native_fbx", "Body", "Rig", 0, 2, 0, 3, 0)
        metadata, influence_texels, _maximum = sparse_render_influence_texels(mesh, [0, 1, 2])
        rest_points = np.frombuffer(mesh["bind_vertices_f32"], dtype=np.float32).reshape((-1, 3))
        rest_palette = build_skin_matrix_palette(
            binding,
            binding["initial_pose"],
            [spec],
            scene_center=(0, 0, 0),
            scene_scale=1.0,
        )
        np.testing.assert_allclose(
            emulate_sparse_gpu_skin_positions(rest_points, metadata, influence_texels, rest_palette),
            rest_points,
            atol=1.0e-5,
        )

        cached_pose = asset.deformation_pose_at_frame(binding, 2, graph=graph)
        self.assertEqual(cached_pose["pose_source"], "baked_exact")
        cached_palette = build_skin_matrix_palette(
            binding,
            cached_pose,
            [spec],
            scene_center=(0, 0, 0),
            scene_scale=1.0,
        )
        cached_points = emulate_sparse_gpu_skin_positions(rest_points, metadata, influence_texels, cached_palette)
        np.testing.assert_allclose(cached_points[0], rest_points[0], atol=1.0e-5)
        np.testing.assert_allclose(cached_points[1:], rest_points[1:] + [100, 0, 0], atol=1.0e-5)

        apply_native_joint_matrix_override(graph, child_id, translation_delta=(100.0, 0.0, 0.0))
        edited_pose = build_native_fbx_deformation_pose(graph, binding)
        edited_palette = build_skin_matrix_palette(
            binding,
            edited_pose,
            [spec],
            scene_center=(0, 0, 0),
            scene_scale=1.0,
        )
        edited_points = emulate_sparse_gpu_skin_positions(rest_points, metadata, influence_texels, edited_palette)
        np.testing.assert_allclose(edited_points[0], rest_points[0], atol=1.0e-5)
        np.testing.assert_allclose(edited_points[1:], rest_points[1:] + [100, 0, 0], atol=1.0e-5)


if __name__ == "__main__":
    unittest.main()
