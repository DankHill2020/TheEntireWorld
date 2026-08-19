from types import SimpleNamespace
import ast
import threading
import unittest
from unittest.mock import patch

from tech_connector.ui.three_d_mesh_painter_widget import DccCameraPossessionWorker, ThreeDMeshPainterViewport


class ViewerCameraSessionFanoutTests(unittest.TestCase):
    def test_camera_navigation_never_calls_a_bridge_on_the_ui_thread(self):
        calls = []
        owner = SimpleNamespace(
            drive_dcc_camera_enabled=True,
            viewport_display_source="compiled",
            request_dcc_camera_possession_async=lambda **kwargs: calls.append(kwargs),
        )

        ThreeDMeshPainterViewport.drive_loaded_dcc_cameras_from_view(owner)

        self.assertEqual(calls, [{"include_unreal": True, "reason": "camera navigation"}])

    def test_camera_possession_executes_independent_sessions_concurrently(self):
        rendezvous = threading.Barrier(2, timeout=1.0)

        class FakeBridge:
            def execute(self, code, timeout=5.0):
                rendezvous.wait()
                return True, code

        requests = [
            {"provider": "maya:7001", "code": "first"},
            {"provider": "maya:7002", "code": "second"},
        ]
        results = []
        worker = DccCameraPossessionWorker(requests)
        worker.finished.connect(results.append)

        with patch(
            "tech_connector.ui.three_d_mesh_painter_widget.scene_snapshot_bridge_for_provider",
            side_effect=lambda provider: FakeBridge(),
        ):
            worker.run()

        self.assertEqual(set(results[0]), {"maya:7001", "maya:7002"})
        self.assertTrue(all(result["ok"] for result in results[0].values()))

    def test_camera_possession_keeps_every_loaded_session_key(self):
        owner = SimpleNamespace(
            _loaded_scene_providers=[
                "maya:7001",
                "maya:7002",
                "blender:7021",
                "motionbuilder:7051",
                "unreal:30010",
                "houdini:7031",
                "unity:7041",
            ],
            _camera_drive_provider_cache=(0.0, [], []),
        )

        supported, skipped = ThreeDMeshPainterViewport._camera_drive_provider_keys(owner, include_unreal=False)

        self.assertEqual(
            supported,
            ["maya:7001", "maya:7002", "blender:7021", "motionbuilder:7051", "houdini:7031", "unity:7041"],
        )
        self.assertEqual(skipped, ["unreal:30010"])

        supported, skipped = ThreeDMeshPainterViewport._camera_drive_provider_keys(owner, include_unreal=True)
        self.assertIn("unreal:30010", supported)
        self.assertIn("houdini:7031", supported)
        self.assertIn("unity:7041", supported)
        self.assertEqual(skipped, [])

    def test_houdini_camera_possession_updates_camera_and_visible_viewports(self):
        payload = {
            "eye": [1.0, 2.0, 3.0],
            "target": [0.0, 1.0, 0.0],
            "up_target": [0.0, 2.0, 0.0],
            "fov_degrees": 45.0,
            "aspect_ratio": 1.777,
        }

        code = ThreeDMeshPainterViewport._houdini_possess_camera_code(None, payload)

        self.assertIn("buildRotateLookAt", code)
        self.assertIn("viewport.setCamera(camera)", code)

    def test_unity_camera_possession_drives_scene_view_without_scene_geometry(self):
        payload = {
            "eye": [1.0, 2.0, 3.0],
            "target": [0.0, 1.0, 0.0],
            "up_target": [0.0, 2.0, 0.0],
            "fov_degrees": 45.0,
        }

        code = ThreeDMeshPainterViewport._unity_possess_camera_code(None, payload)

        self.assertIn("SceneView.lastActiveSceneView", code)
        self.assertIn("SetPositionAndRotation", code)
        self.assertNotIn("GameObject", code)

    def test_camera_possession_adapters_preserve_authority_aspect(self):
        payload = {
            "eye": [1.0, 2.0, 3.0],
            "target": [0.0, 1.0, 0.0],
            "up_target": [0.0, 2.0, 0.0],
            "fov_degrees": 52.0,
            "aspect_ratio": 2.39,
            "near_clip": 0.1,
            "far_clip": 10000.0,
        }

        maya = ThreeDMeshPainterViewport._maya_possess_camera_code(None, payload)
        blender = ThreeDMeshPainterViewport._blender_possess_camera_code(None, payload)
        houdini = ThreeDMeshPainterViewport._houdini_possess_camera_code(None, payload)
        unreal = ThreeDMeshPainterViewport._unreal_possess_camera_code(None, payload)
        motionbuilder = ThreeDMeshPainterViewport._motionbuilder_possess_camera_code(None, payload)

        for source in (maya, blender, houdini, unreal, motionbuilder):
            ast.parse(source)
            self.assertIn("aspect_ratio", source)
        self.assertIn("verticalFilmAperture", maya)
        self.assertIn("defaultResolution.deviceAspectRatio", maya)
        self.assertIn("angle_y", blender)
        self.assertIn("render.resolution_x", blender)
        self.assertIn('parm("resx")', houdini)
        self.assertIn("horizontal_fov", unreal)
        self.assertIn("FieldOfViewY.Data", motionbuilder)

    def test_maya_camera_authority_uses_output_gate_and_film_fit(self):
        code = ThreeDMeshPainterViewport._maya_read_camera_authority_code(None, "shotCamera")

        ast.parse(code)
        self.assertIn("defaultResolution.deviceAspectRatio", code)
        self.assertIn("film_fit", code)
        self.assertIn("effective_vertical_aperture", code)


if __name__ == "__main__":
    unittest.main()
