import unittest
from unittest.mock import patch

from engine.request_context import RequestContext
from services.dcc_execution_service import (
    build_dcc_execution_request,
    DccExecutionRequest,
    MayaExecutionAdapter,
    UnrealExecutionAdapter,
)
from services.prompt_dispatch_service import CAP_DCC_CONNECTION, PromptDispatchService


class DccDirectBridgeCapabilityTests(unittest.TestCase):
    def test_unapproved_confirmation_does_not_probe_direct_dcc_connection(self):
        service = PromptDispatchService()
        decision = {
            "execution_environment": "maya",
            "host": "maya",
            "requires_dcc_connection": True,
            "requires_confirmation": True,
            "approved": False,
        }
        context = RequestContext(text="In Maya create a locator named prompt_smoke_locator.")

        with patch.object(service, "_has_direct_dcc_connection", side_effect=AssertionError("should not probe before approval")):
            missing = service._missing_capabilities({CAP_DCC_CONNECTION}, decision, context)

        self.assertEqual(set(), missing)

    def test_maya_port_phrase_is_extracted_into_execution_request(self):
        decision = {
            "execution_environment": "maya",
            "host": "maya",
            "target_identifier": "scene.move",
            "callable_name": "ai_studio.maya.generated.scene_move",
            "operation_mode": "execute",
            "mutation_scope": "scene_object",
            "approved": True,
            "keyword_args": {"objects": ["pelvis_ctrl"], "translation": [0, 1, 0]},
        }
        context = RequestContext(text="In Maya use port 7001 and move pelvis_ctrl up.")

        request = build_dcc_execution_request(decision, context)

        self.assertEqual(request.keyword_args["maya_port"], 7001)

    def test_maya_scene_path_phrase_is_extracted_into_execution_request(self):
        decision = {
            "execution_environment": "maya",
            "host": "maya",
            "target_identifier": "scene.move",
            "callable_name": "ai_studio.maya.generated.scene_move",
            "operation_mode": "execute",
            "mutation_scope": "scene_object",
            "approved": True,
            "keyword_args": {"objects": ["pelvis_ctrl"], "translation": [0, 1, 0]},
        }
        context = RequestContext(text="Use the Maya session with C:/chars/omari_rig.mb and move pelvis_ctrl up.")
        sessions = [
            {"ok": True, "port": 7001, "pid": 111, "scene": "C:/chars/other.ma", "selection": []},
            {"ok": True, "port": 7002, "pid": 222, "scene": "C:/chars/omari_rig.mb", "selection": []},
        ]
        with patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=sessions):
            request = build_dcc_execution_request(decision, context)

        self.assertEqual(request.keyword_args["maya_port"], 7002)

    def test_maya_scene_basename_phrase_can_choose_session(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
            approved=True,
        )
        context = RequestContext(text="Use the Maya session with omari_rig.mb and move pelvis_ctrl.")
        sessions = [
            {"ok": True, "port": 7001, "pid": 111, "scene": "C:/chars/other.ma", "selection": []},
            {"ok": True, "port": 7002, "pid": 222, "scene": "C:/chars/omari_rig.mb", "selection": []},
        ]
        with patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=sessions):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)

        self.assertTrue(result.ok)
        self.assertEqual(request.keyword_args["maya_port"], 7002)

    def test_maya_unique_scene_token_can_choose_session(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
            approved=True,
        )
        context = RequestContext(text="Use the Omari file and move pelvis_ctrl.")
        sessions = [
            {"ok": True, "port": 7001, "pid": 111, "scene": "", "selection": []},
            {"ok": True, "port": 7002, "pid": 222, "scene": "C:/chars/omari_rig.mb", "selection": []},
        ]
        with patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=sessions):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)

        self.assertTrue(result.ok)
        self.assertEqual(request.keyword_args["maya_port"], 7002)

    def test_maya_ambiguous_scene_token_still_requires_user_choice(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
            approved=True,
        )
        context = RequestContext(text="Use the cinematic file and move camera_ctrl.")
        sessions = [
            {"ok": True, "port": 7001, "pid": 111, "scene": "C:/shots/cinematic_a.ma", "selection": []},
            {"ok": True, "port": 7002, "pid": 222, "scene": "C:/shots/cinematic_b.ma", "selection": []},
        ]
        with patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=sessions):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].capability, "maya_session_selection")

    def test_maya_read_only_query_can_use_direct_bridge_without_window(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="query",
            target_type="dcc_query",
            target_identifier="selection",
            mutation_scope="read_only",
        )
        context = RequestContext(text="In Maya what is selected?")
        with (
            patch("services.dcc_execution_service._maya_direct_bridge_available", return_value=True),
            patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=[{"ok": True, "port": 7001}]),
        ):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])

    def test_unapproved_maya_known_mutation_reaches_confirmation_without_window(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
        )
        context = RequestContext(text="Move pelvis_ctrl in Maya")
        with (
            patch("services.dcc_execution_service._maya_direct_bridge_available", return_value=True),
            patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=[{"ok": True, "port": 7001}]),
        ):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])

    def test_approved_maya_known_mutation_can_use_direct_bridge_without_window(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
            approved=True,
        )
        context = RequestContext(text="Move pelvis_ctrl in Maya")
        with (
            patch("services.dcc_execution_service._maya_direct_bridge_available", return_value=True),
            patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=[{"ok": True, "port": 7001}]),
        ):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)
        self.assertTrue(result.ok)

    def test_approved_maya_locator_creation_can_use_direct_bridge_without_window(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.create_locator",
            mutation_scope="scene_object",
            approved=True,
        )
        context = RequestContext(text="In Maya create a locator named prompt_smoke_locator and select it.")
        with (
            patch("services.dcc_execution_service._maya_direct_bridge_available", return_value=True),
            patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=[{"ok": True, "port": 7001}]),
        ):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)
        self.assertTrue(result.ok)

    def test_multiple_maya_sessions_require_user_choice(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
            approved=True,
        )
        context = RequestContext(text="Move pelvis_ctrl in Maya")
        sessions = [
            {"ok": True, "port": 7001, "pid": 111, "scene": "C:/chars/A.ma", "selection": []},
            {"ok": True, "port": 7002, "pid": 222, "scene": "C:/chars/B.ma", "selection": ["pelvis_ctrl"]},
        ]
        with patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=sessions):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].capability, "maya_session_selection")
        self.assertIn("scene `C:/chars/A.ma`", result.failures[0].required_user_action)
        self.assertIn("C:/chars/B.ma", result.failures[0].required_user_action)

    def test_multiple_maya_sessions_allow_explicit_port_choice(self):
        request = DccExecutionRequest(
            execution_environment="maya",
            operation_mode="execute",
            target_type="dcc_callable",
            target_identifier="scene.move",
            mutation_scope="scene_object",
            approved=True,
            keyword_args={"maya_port": 7002},
        )
        context = RequestContext(text="Move pelvis_ctrl in Maya using port 7002")
        sessions = [
            {"ok": True, "port": 7001, "pid": 111, "scene": "C:/chars/A.ma", "selection": []},
            {"ok": True, "port": 7002, "pid": 222, "scene": "C:/chars/B.ma", "selection": ["pelvis_ctrl"]},
        ]
        with patch("services.dcc_execution_service._maya_direct_bridge_sessions", return_value=sessions):
            result = MayaExecutionAdapter("maya").check_capabilities(request, context)

        self.assertTrue(result.ok)

    def test_unreal_read_only_project_snapshot_can_use_direct_bridge_without_window(self):
        request = DccExecutionRequest(
            execution_environment="unreal",
            operation_mode="execute",
            target_type="unreal_capability",
            target_identifier="project.snapshot",
            mutation_scope="read_only",
        )
        context = RequestContext(text="In Unreal inspect the current project. Do not edit anything.")
        with patch("services.dcc_execution_service._unreal_direct_bridge_available", return_value=True):
            result = UnrealExecutionAdapter("unreal").check_capabilities(request, context)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])

    def test_unreal_project_snapshot_query_uses_direct_snapshot_operation(self):
        request = DccExecutionRequest(
            execution_environment="unreal",
            operation_mode="query",
            target_type="unreal_capability",
            target_identifier="project.snapshot",
            mutation_scope="read_only",
            original_prompt="In Unreal, take a project snapshot and report loaded level.",
        )
        adapter = UnrealExecutionAdapter("unreal")
        with patch.object(
            adapter,
            "_run_unreal_python",
            return_value=(True, {"current_level": "/Game/Maps/TestMap", "selected_actors": [], "selected_assets": [], "asset_counts": {"Blueprint": 3}}),
        ):
            result = adapter.query(request, RequestContext(text=request.original_prompt))

        self.assertEqual("completed", result.status)
        self.assertEqual("project.snapshot", result.structured_data["operation"])
        self.assertIn("Unreal project inspection report", result.user_message)

    def test_unreal_graph_mutation_still_requires_foreground_window(self):
        request = DccExecutionRequest(
            execution_environment="unreal",
            operation_mode="execute",
            target_type="unreal_capability",
            target_identifier="unreal_semantic_graph_modification",
            mutation_scope="graph_asset",
        )
        context = RequestContext(text="In Unreal add a Branch node to BP_LesterPhoenix.")
        with patch("services.dcc_execution_service._unreal_direct_bridge_available", return_value=True):
            result = UnrealExecutionAdapter("unreal").check_capabilities(request, context)
        self.assertFalse(result.ok)
        self.assertIn("foreground_window", [failure.capability for failure in result.failures])

    def test_approved_unreal_graph_patch_can_use_direct_bridge_without_window(self):
        request = DccExecutionRequest(
            execution_environment="unreal",
            operation_mode="execute",
            target_type="unreal_capability",
            target_identifier="unreal_semantic_graph_modification",
            mutation_scope="graph_asset",
            approved=True,
        )
        context = RequestContext(text="In Unreal add a Print String node to BP_LesterPhoenix.")
        with patch("services.dcc_execution_service._unreal_direct_bridge_available", return_value=True):
            result = UnrealExecutionAdapter("unreal").check_capabilities(request, context)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
