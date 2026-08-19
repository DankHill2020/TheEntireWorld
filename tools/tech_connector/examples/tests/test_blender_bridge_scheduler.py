import array
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.bridges.blender.blender_bridge import (
    ADDON_SOURCE_CODE,
    BlenderBridge,
    decode_blender_snapshot_geometry,
    install_to_version,
)


class BlenderBridgeSchedulerTests(unittest.TestCase):
    def test_addon_uses_low_latency_clamped_main_thread_polling(self):
        self.assertIn('TECH_CONNECTOR_BLENDER_BRIDGE_POLL_SECONDS', ADDON_SOURCE_CODE)
        self.assertIn('max(0.001, min(0.05, value))', ADDON_SOURCE_CODE)
        self.assertIn('return _BRIDGE_POLL_SECONDS', ADDON_SOURCE_CODE)
        self.assertNotIn('return 0.05', ADDON_SOURCE_CODE)

    def test_addon_selects_next_available_port_for_multiple_sessions(self):
        self.assertIn('for candidate in range(PORT, PORT + _bridge_port_scan_count())', ADDON_SOURCE_CODE)
        self.assertIn('_bound_port = candidate', ADDON_SOURCE_CODE)

    def test_addon_bounds_queue_clients_payloads_and_tick_work(self):
        compile(ADDON_SOURCE_CODE, "<blender_addon>", "exec")
        self.assertIn('queue.Queue(maxsize=_MAX_PENDING_JOBS)', ADDON_SOURCE_CODE)
        self.assertIn('while processed < _MAX_JOBS_PER_TICK', ADDON_SOURCE_CODE)
        self.assertIn('if len(raw) > _MAX_REQUEST_BYTES', ADDON_SOURCE_CODE)
        self.assertIn('_client_slots.acquire(blocking=False)', ADDON_SOURCE_CODE)
        self.assertIn('job["canceled"] = True', ADDON_SOURCE_CODE)
        self.assertIn('_cancel_pending_jobs("Blender bridge stopped', ADDON_SOURCE_CODE)

    def test_find_ports_scans_range_and_keeps_preference_first(self):
        bridge = BlenderBridge()
        with (
            patch("tech_connector.bridges.blender.blender_bridge.preferred_session_port", return_value=7023),
            patch.dict(os.environ, {"BLENDER_COMMAND_PORT_SCAN_COUNT": "4"}, clear=False),
            patch.object(bridge, "_is_port_open", side_effect=lambda _host, port: port in {7021, 7023}),
        ):
            self.assertEqual([7023, 7021], bridge.find_ports())

    def test_session_info_is_bound_to_requested_port(self):
        bridge = BlenderBridge()
        payload = '{"pid": 42, "version": "5.1", "scene": "shot.blend", "selection": []}'
        with patch.object(bridge, "execute_on_port", return_value=(True, payload)) as execute:
            info = bridge.session_info(port=7024)
        self.assertTrue(info["ok"])
        self.assertEqual(7024, info["port"])
        execute.assert_called_once()
        self.assertEqual(7024, execute.call_args.kwargs["port"])

    def test_execute_cancels_before_opening_socket(self):
        bridge = BlenderBridge()
        canceled = threading.Event()
        canceled.set()
        with patch("tech_connector.bridges.blender.blender_bridge.socket.socket") as socket_factory:
            ok, message = bridge.execute_on_port("print('late')", port=7021, cancel_event=canceled)
        self.assertFalse(ok)
        self.assertIn("canceled", message.lower())
        socket_factory.assert_not_called()

    def test_execute_sends_server_deadline_and_uses_large_receive_chunks(self):
        class FakeSocket:
            def __init__(self):
                self.sent = b""
                self.recv_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                pass

            def sendall(self, payload):
                self.sent = payload

            def recv(self, size):
                self.recv_sizes.append(size)
                return b'{"ok": true, "result": "OK"}\n'

        bridge = BlenderBridge()
        fake_socket = FakeSocket()
        with patch("tech_connector.bridges.blender.blender_bridge.socket.socket", return_value=fake_socket):
            ok, result = bridge.execute_on_port("print('ok')", port=7021, timeout=4.0)
        self.assertTrue(ok)
        self.assertEqual("OK", result)
        payload = json.loads(fake_socket.sent.decode("utf-8"))
        self.assertAlmostEqual(3.8, payload["timeout_seconds"])
        self.assertEqual([262144], fake_socket.recv_sizes)

    def test_execute_rejects_oversized_response(self):
        class OversizedSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                pass

            def sendall(self, _payload):
                pass

            def recv(self, _size):
                return b"x" * 2048 + b"\n"

        bridge = BlenderBridge()
        with (
            patch.dict(os.environ, {"TECH_CONNECTOR_BLENDER_MAX_RESPONSE_BYTES": "1024"}),
            patch("tech_connector.bridges.blender.blender_bridge.socket.socket", return_value=OversizedSocket()),
        ):
            ok, result = bridge.execute_on_port("print('large')", port=7021)
        self.assertFalse(ok)
        self.assertIn("size limit", result)

    def test_binary_scene_geometry_decodes_vertices_faces_and_uvs(self):
        chunks = bytearray()

        def append(values):
            offset = len(chunks)
            chunks.extend(values.tobytes())
            return offset

        vertices = array.array("f", [0, 0, 0, 1, 0, 0, 0, 1, 0])
        face_counts = array.array("I", [3])
        face_indices = array.array("I", [0, 1, 2])
        uvs = array.array("f", [0, 0, 1, 0, 0, 1])
        face_uv_indices = array.array("I", [0, 1, 2])
        offsets = [append(values) for values in (vertices, face_counts, face_indices, uvs, face_uv_indices)]
        geometry = {
            "representation": "mesh",
            "vertex_encoding": "f32-file-array",
            "vertex_byte_offset": offsets[0],
            "vertex_float_count": len(vertices),
            "face_encoding": "u32-file-counts-indices",
            "face_count_byte_offset": offsets[1],
            "face_count_count": len(face_counts),
            "face_index_byte_offset": offsets[2],
            "face_index_count": len(face_indices),
            "uv_encoding": "f32-file-array",
            "uv_byte_offset": offsets[3],
            "uv_float_count": len(uvs),
            "face_uv_encoding": "u32-file-indices",
            "face_uv_byte_offset": offsets[4],
            "face_uv_index_count": len(face_uv_indices),
        }
        snapshot = decode_blender_snapshot_geometry(
            {"objects": [{"geometry": geometry}]},
            bytes(chunks),
        )
        self.assertEqual([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], geometry["vertices"])
        self.assertEqual([[0, 1, 2]], geometry["faces"])
        self.assertEqual([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], geometry["uvs"])
        self.assertEqual([[0, 1, 2]], geometry["face_uv_indices"])
        self.assertEqual(len(chunks), snapshot["binary_geometry_bytes"])

    def test_binary_scene_geometry_rejects_out_of_bounds_sidecar(self):
        snapshot = {
            "objects": [{"geometry": {
                "vertex_encoding": "f32-file-array",
                "vertex_byte_offset": 8,
                "vertex_float_count": 3,
            }}]
        }
        with self.assertRaisesRegex(ValueError, "exceeds"):
            decode_blender_snapshot_geometry(snapshot, b"tiny")

    def test_install_does_not_report_success_for_stale_permission_denied_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            version_root = Path(temp_dir)
            addon = version_root / "scripts" / "addons" / "the_entire_world_ai_studio_bridge.py"
            startup = version_root / "scripts" / "startup" / "the_entire_world_ai_studio_bridge_startup.py"
            addon.parent.mkdir(parents=True)
            startup.parent.mkdir(parents=True)
            addon.write_text("stale", encoding="utf-8")
            startup.write_text("stale", encoding="utf-8")
            with patch.object(Path, "write_text", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    install_to_version(version_root)


if __name__ == "__main__":
    unittest.main()
