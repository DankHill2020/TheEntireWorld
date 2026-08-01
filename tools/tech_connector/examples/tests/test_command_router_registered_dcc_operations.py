from __future__ import annotations

import json
import unittest

from tech_connector.router.command_router import CommandRouter


class FakeBridge:
    def __init__(self):
        self.calls = []

    def call_function(self, entry_point, args=None, kwargs=None):
        self.calls.append((entry_point, list(args or []), dict(kwargs or {})))
        return True, {"called": entry_point, "kwargs": dict(kwargs or {})}

    def execute(self, code, timeout=60):
        self.calls.append(("execute", [], {"code": code, "timeout": timeout}))
        return True, '{"ok": true}'


class RegisteredDccOperationRouterTests(unittest.TestCase):
    def test_maya_registered_operation_uses_maya_bridge_adapter(self) -> None:
        router = CommandRouter()
        router.maya = FakeBridge()

        label, ok, raw = router.execute_registered_dcc_operation(
            "maya",
            "material.assign",
            {"material_name": "M_Test", "objects": ["meshA"]},
        )

        self.assertEqual("Maya Registered Operation", label)
        self.assertTrue(ok, raw)
        call_name, args, kwargs = router.maya.calls[-1]
        self.assertEqual("execute", call_name)
        self.assertEqual([], args)
        self.assertIn("material_name", kwargs["code"])
        self.assertIn("M_Test", kwargs["code"])
        self.assertIn("meshA", kwargs["code"])
        payload = json.loads(raw)
        self.assertEqual("completed", payload["status"])
        self.assertEqual("maya", payload["execution_environment"])

    def test_blender_registered_operation_uses_blender_bridge_adapter(self) -> None:
        router = CommandRouter()
        router.blender = FakeBridge()

        label, ok, raw = router.execute_registered_dcc_operation(
            "blender",
            "blender.scan_animation",
            {"armature_name": "MannyRig"},
        )

        self.assertEqual("Blender Registered Operation", label)
        self.assertTrue(ok, raw)
        call_name, args, kwargs = router.blender.calls[-1]
        self.assertEqual("execute", call_name)
        self.assertEqual([], args)
        self.assertIn('operation = \'blender.scan_animation\'', kwargs["code"])
        self.assertIn("MannyRig", kwargs["code"])
        payload = json.loads(raw)
        self.assertEqual("completed", payload["status"])
        self.assertEqual("blender", payload["execution_environment"])

    def test_blender_package_operation_uses_bridge_call_function(self) -> None:
        router = CommandRouter()
        router.blender = FakeBridge()

        label, ok, raw = router.execute_registered_dcc_operation(
            "blender",
            "render.render_scene",
            {"output_path": "C:/tmp/render.png"},
        )

        self.assertEqual("Blender Registered Operation", label)
        self.assertTrue(ok, raw)
        self.assertEqual(
            (
                "blender_tools.render.render_scene",
                [],
                {"output_path": "C:/tmp/render.png"},
            ),
            router.blender.calls[-1],
        )
        payload = json.loads(raw)
        self.assertEqual("completed", payload["status"])

    def test_registered_operation_reports_missing_required_arguments(self) -> None:
        router = CommandRouter()
        router.maya = FakeBridge()

        label, ok, raw = router.execute_registered_dcc_operation("maya", "material.assign", {})

        self.assertEqual("Maya Registered Operation", label)
        self.assertFalse(ok)
        payload = json.loads(raw)
        self.assertEqual("capability_failure", payload["status"])
        self.assertEqual("arguments_resolved", payload["failures"][0]["capability"])
        self.assertFalse(router.maya.calls)


if __name__ == "__main__":
    unittest.main()
