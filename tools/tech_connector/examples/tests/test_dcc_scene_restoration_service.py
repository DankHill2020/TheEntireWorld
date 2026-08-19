import tempfile
import threading
import unittest
from pathlib import Path

from tech_connector.game_engine.integration.dcc_scene_restoration_service import (
    DccRestoreLaunch,
    dcc_launch_command,
    restore_scene_sources,
)
from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    reconcile_scene_sources,
    source_snapshot_blob_name,
    stable_scene_source_id,
)


class _FakeProcess:
    def __init__(self, pid=4242):
        self.pid = pid

    def poll(self):
        return None


class DccSceneRestorationServiceTests(unittest.TestCase):
    def test_stable_source_identity_ignores_transient_port_for_saved_files(self):
        first = stable_scene_source_id("maya", "C:/show/shot.ma", "maya:7001")
        second = stable_scene_source_id("maya", "C:/show/shot.ma", "maya:7012")

        self.assertEqual(first, second)
        self.assertEqual(source_snapshot_blob_name(first), f"scene_sources/{first}/snapshot.json")

    def test_reconcile_launches_instead_of_replacing_unknown_or_dirty_session(self):
        with tempfile.TemporaryDirectory() as directory:
            scene_path = Path(directory) / "shot.blend"
            scene_path.write_bytes(b"BLENDER")
            document = FederatedSceneDocument(sources=[{
                "provider": "blender",
                "session_key": "blender:7021",
                "source_path": str(scene_path),
            }])
            result = reconcile_scene_sources(document, [{
                "provider": "blender",
                "key": "blender:7021",
                "scene": "C:/other.blend",
                "scene_modified": True,
            }])

        self.assertEqual(result[0]["action"], "launch_source")
        self.assertIsNone(result[0]["session"])

    def test_reconcile_can_reuse_explicitly_clean_empty_session(self):
        with tempfile.TemporaryDirectory() as directory:
            scene_path = Path(directory) / "shot.ma"
            scene_path.write_text("// maya", encoding="ascii")
            document = FederatedSceneDocument(sources=[{
                "provider": "maya",
                "session_key": "maya:7001",
                "source_path": str(scene_path),
            }])
            result = reconcile_scene_sources(document, [{
                "provider": "maya",
                "key": "maya:7008",
                "scene": "",
                "scene_modified": False,
            }])

        self.assertEqual(result[0]["action"], "open_source")
        self.assertEqual(result[0]["session_key"], "maya:7008")

    def test_reconcile_reports_source_changed_since_scene_save(self):
        with tempfile.TemporaryDirectory() as directory:
            scene_path = Path(directory) / "shot.ma"
            scene_path.write_text("// changed maya scene", encoding="ascii")
            document = FederatedSceneDocument(sources=[{
                "provider": "maya",
                "session_key": "maya:7001",
                "source_path": str(scene_path),
                "source_fingerprint": {
                    "exists": True,
                    "size": 1,
                    "mtime_ns": 1,
                    "head_sha256": "old",
                },
            }])
            result = reconcile_scene_sources(document, [{
                "provider": "maya",
                "key": "maya:7001",
                "scene": str(scene_path),
                "scene_modified": False,
            }])

        self.assertEqual(result[0]["action"], "attach")
        self.assertTrue(result[0]["source_changed"])

    def test_cached_only_policy_never_discovers_or_launches(self):
        calls = []
        report = restore_scene_sources(
            [{"provider": "maya", "source_path": "C:/show/shot.ma"}],
            policy="cached_only",
            discover_sessions=lambda: calls.append("discover") or [],
            open_source=lambda key, path: (False, "unexpected"),
            launch_source=lambda source: calls.append("launch"),
        )

        self.assertEqual(calls, [])
        self.assertEqual(report["entries"][0]["status"], "cached_only")

    def test_restore_launches_separate_process_and_captures_matching_session(self):
        with tempfile.TemporaryDirectory() as directory:
            scene_path = Path(directory) / "shot.blend"
            scene_path.write_bytes(b"BLENDER")
            source = {
                "source_id": "blender-source",
                "provider": "blender",
                "source_path": str(scene_path),
                "session_key": "blender:7021",
            }
            discovery_count = 0

            def discover():
                nonlocal discovery_count
                discovery_count += 1
                if discovery_count < 2:
                    return [{
                        "provider": "blender",
                        "key": "blender:7021",
                        "scene": "C:/other.blend",
                        "scene_modified": True,
                        "process_id": 111,
                    }]
                return [{
                    "provider": "blender",
                    "key": "blender:7022",
                    "scene": str(scene_path),
                    "scene_modified": False,
                    "process_id": 4242,
                }]

            def launch(_source):
                return DccRestoreLaunch("blender", str(scene_path), "blender.exe", _FakeProcess(), 0.0)

            report = restore_scene_sources(
                [source],
                policy="automatic",
                discover_sessions=discover,
                open_source=lambda key, path: (False, "must not replace dirty session"),
                capture_snapshot=lambda key: (True, {"provider_id": key, "objects": []}),
                launch_source=launch,
                launch_timeout=1.0,
            )

        self.assertEqual(report["entries"][0]["status"], "launched")
        self.assertEqual(report["session_keys"], ["blender:7022"])
        self.assertIn("blender:7022", report["snapshots"])
        self.assertEqual(len(report["launches"]), 1)

    def test_cancellation_stops_before_source_work(self):
        canceled = threading.Event()
        canceled.set()
        report = restore_scene_sources(
            [{"provider": "maya", "source_path": "C:/missing.ma"}],
            policy="automatic",
            discover_sessions=lambda: [],
            open_source=lambda key, path: (False, "unexpected"),
            cancel_event=canceled,
        )

        self.assertTrue(report["canceled"])
        self.assertEqual(report["entries"], [])

    def test_launch_commands_open_the_linked_source_directly(self):
        maya = dcc_launch_command("maya", "maya.exe", "C:/show/shot.ma")
        blender = dcc_launch_command("blender", "blender.exe", "C:/show/shot.blend")
        unity = dcc_launch_command("unity", "Unity.exe", "C:/show/UnityProject/Assets/shot.unity")

        self.assertEqual(maya[1], "-file")
        self.assertTrue(maya[2].lower().endswith("shot.ma"))
        self.assertTrue(blender[1].lower().endswith("shot.blend"))
        self.assertEqual(unity[1], "-projectPath")
        self.assertTrue(unity[2].replace("\\", "/").lower().endswith("unityproject"))


if __name__ == "__main__":
    unittest.main()
