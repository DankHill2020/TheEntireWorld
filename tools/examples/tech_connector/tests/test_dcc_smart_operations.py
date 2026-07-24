import unittest

from tech_connector.engine.request_engine import RequestEngine
from tech_connector.engine.request_context import RequestContext
from tech_connector.services.dcc.dcc_operation_service import (
    blender_operation_code,
    build_dcc_operation_params,
    dcc_prompt_to_operation,
    maya_operation_code,
    resolve_registered_dcc_operation_key,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.dcc.dcc_execution_service import build_dcc_execution_request, default_dcc_execution_adapters


class TestDccSmartOperations(unittest.TestCase):
    def test_unique_registered_leaf_name_is_canonicalized(self):
        self.assertEqual(
            resolve_registered_dcc_operation_key("maya", "move"),
            "scene.move",
        )
        self.assertEqual(
            resolve_registered_dcc_operation_key("maya", "fake_operation"),
            "",
        )

    def test_maya_constraint_routes_to_generated_operation(self):
        prompt = "Maya parent constrain hand_CTRL to wrist_JNT with offset"
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "constraints.create")
        params = build_dcc_operation_params("maya", "constraints.create", prompt)
        self.assertEqual(params["constraint_type"], "parent")
        self.assertEqual(params["driven"], "hand_CTRL")
        self.assertEqual(params["targets"], ["wrist_JNT"])
        code = maya_operation_code("constraints.create", params)
        self.assertIn("cmds.parentConstraint", code)

    def test_maya_api_call_supports_cmds_and_openmaya(self):
        cmds_prompt = "Maya call maya.cmds.setAttr kwargs {\"lock\": true}"
        self.assertEqual(dcc_prompt_to_operation("maya", cmds_prompt), "api.call")
        cmds_params = build_dcc_operation_params("maya", "api.call", cmds_prompt)
        self.assertEqual(cmds_params["function"], "maya.cmds.setAttr")

        om_prompt = "Maya use maya.api.OpenMaya.MSelectionList"
        self.assertEqual(dcc_prompt_to_operation("maya", om_prompt), "api.call")
        om_params = build_dcc_operation_params("maya", "api.call", om_prompt)
        self.assertEqual(om_params["function"], "maya.api.OpenMaya.MSelectionList")

    def test_maya_skin_and_material_routes(self):
        skin_prompt = "Maya bind skin mesh body_GEO with root_JNT spine_JNT"
        self.assertEqual(dcc_prompt_to_operation("maya", skin_prompt), "skin.bind")
        skin_params = build_dcc_operation_params("maya", "skin.bind", skin_prompt)
        self.assertEqual(skin_params["mesh"], "body_GEO")
        self.assertIn("root_JNT", skin_params["influences"])

        mat_prompt = "Maya create material heroMat red"
        self.assertEqual(dcc_prompt_to_operation("maya", mat_prompt), "material.create")
        mat_params = build_dcc_operation_params("maya", "material.create", mat_prompt)
        self.assertEqual(mat_params["material_name"], "heroMat")
        self.assertEqual(tuple(mat_params["color"]), (1.0, 0.0, 0.0))

    def test_maya_biped_rfl_template_routes_to_callable_loader(self):
        prompt = (
            'Maya reference the biped rig template with RFL joints from '
            '"C:/depot/ArtSource/Rigs/rig_template.ma" namespace TC_TemplateRig'
        )

        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "rigging.load_biped_template")
        params = build_dcc_operation_params("maya", "rigging.load_biped_template", prompt)
        self.assertEqual(params["template_path"], "C:/depot/ArtSource/Rigs/rig_template.ma")
        self.assertEqual(params["namespace"], "TC_TemplateRig")
        self.assertTrue(params["reference"])

        code = maya_operation_code("rigging.load_biped_template", params)
        self.assertIn("from maya_tools.Rigging import rig_template", code)
        self.assertIn("rig_template.load_biped_rig_template", code)
        self.assertIn("TC_TemplateRig", code)

        decision = classify_prompt_route(prompt)
        self.assertEqual(decision.route, "dcc_execute")
        self.assertEqual(decision.host, "maya")
        self.assertEqual(decision.target_identifier, "rigging.load_biped_template")
        self.assertTrue(decision.requires_confirmation)

    def test_maya_current_biped_template_control_rig_routes_to_create_rig(self):
        prompt = "In Maya, build the full biped control rig for the currently open rig template skeleton with RFL joints."

        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "rigging.create_rig")
        params = build_dcc_operation_params("maya", "rigging.create_rig", prompt)
        self.assertNotIn("character_name", params)
        code = maya_operation_code("rigging.create_rig", params)
        self.assertIn("setup_hik.create_rig_mapping", code)
        self.assertIn("create_rig.create_rig_from_mapping", code)
        decision = classify_prompt_route(prompt)
        self.assertEqual(decision.route, "dcc_execute")
        self.assertEqual(decision.host, "maya")
        self.assertEqual(decision.target_identifier, "rigging.create_rig")
        self.assertTrue(decision.requires_confirmation)
        goals = (decision.task_graph or {}).get("ordered_goals") or []
        goal_ids = [goal.get("task_id") or goal.get("goal_id") for goal in goals]
        self.assertEqual(
            goal_ids,
            [
                "inspect_maya_rig_scene",
                "resolve_hik_body_face_mapping",
                "create_core_body_modules",
                "create_face_modules",
                "validate_created_rig",
            ],
        )
        by_id = {goal.get("task_id") or goal.get("goal_id"): goal for goal in goals}
        self.assertEqual(by_id["resolve_hik_body_face_mapping"]["depends_on"], ["inspect_maya_rig_scene"])
        self.assertEqual(by_id["create_core_body_modules"]["depends_on"], ["resolve_hik_body_face_mapping"])
        self.assertEqual(
            by_id["create_face_modules"]["depends_on"],
            ["resolve_hik_body_face_mapping", "create_core_body_modules"],
        )
        self.assertEqual(by_id["validate_created_rig"]["depends_on"], ["create_core_body_modules", "create_face_modules"])

    def test_blender_scripting_routes_without_blender_tools(self):
        prompt = "Blender run bpy.ops.mesh.primitive_cube_add kwargs {\"size\": 2}"
        self.assertEqual(dcc_prompt_to_operation("blender", prompt), "api.call")
        params = build_dcc_operation_params("blender", "api.call", prompt)
        self.assertEqual(params["function"], "bpy.ops.mesh.primitive_cube_add")
        code = blender_operation_code("api.call", params)
        self.assertIn("Only bpy.* calls", code)

    def test_prompt_route_uses_known_maya_and_blender_operations(self):
        maya_decision = classify_prompt_route("Maya connect ctrl.tx to joint.rx")
        self.assertEqual(maya_decision.route, "dcc_execute")
        self.assertEqual(maya_decision.host, "maya")
        self.assertEqual(maya_decision.target_identifier, "node.connect_attr")
        self.assertEqual(maya_decision.keyword_args["source_attr"], "ctrl.tx")

    def test_maya_bone_name_question_routes_to_read_only_query(self):
        decision = classify_prompt_route("In Maya what is the first bone name you can find?")
        self.assertEqual(decision.route, "dcc_query")
        self.assertEqual(decision.host, "maya")
        self.assertEqual(decision.target_identifier, "scene.list_joints")
        self.assertEqual(decision.mutation_scope, "read_only")
        self.assertFalse(decision.requires_confirmation)
        self.assertTrue(decision.keyword_args["first_only"])

    def test_maya_joint_list_first_ten_is_limited_list_not_first_only(self):
        prompt = "In Maya list the first 10 joints in the current skeleton."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.list_joints")
        params = build_dcc_operation_params("maya", "scene.list_joints", prompt)

        self.assertFalse(params["first_only"])
        self.assertEqual(params["limit"], 10)

    def test_maya_selection_query_uses_cmds_ls_flags(self):
        prompt = "In Maya what is currently selected?"
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.ls")
        params = build_dcc_operation_params("maya", "scene.ls", prompt)

        self.assertTrue(params["selection"])

    def test_maya_frame_selected_routes_to_navigation_before_selection_query(self):
        prompt = "In Maya frame selected object TC_PROMPT_PROBE_cube in the viewport."

        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "navigation.frame_selection")

    def test_maya_scene_type_query_uses_cmds_ls_type(self):
        prompt = "In Maya list the first 5 meshes in the scene."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.ls")
        params = build_dcc_operation_params("maya", "scene.ls", prompt)

        self.assertEqual(params["type"], "mesh")
        self.assertEqual(params["limit"], 5)

    def test_maya_scene_ls_parses_contains_pattern_and_up_to_limit(self):
        prompt = "In Maya list up to 5 transform nodes whose names contain TC_LIVE_PROMPT. Do not change the scene."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.ls")
        params = build_dcc_operation_params("maya", "scene.ls", prompt)

        self.assertEqual(params["type"], "transform")
        self.assertEqual(params["name_patterns"], ["*TC_LIVE_PROMPT*"])
        self.assertEqual(params["limit"], 5)
        self.assertFalse(params["first_only"])

    def test_maya_control_query_uses_name_pattern_not_fake_type(self):
        prompt = "In Maya list controls in the scene."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.ls")
        params = build_dcc_operation_params("maya", "scene.ls", prompt)

        self.assertIn("*ctrl*", params["name_patterns"])
        self.assertNotEqual(params.get("type"), "control")

    def test_maya_primitive_params_include_name_and_size(self):
        prompt = "In Maya create a cube named TC_PROMPT_PROBE_cube size 1.0."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "modeling.create_primitive")
        params = build_dcc_operation_params("maya", "modeling.create_primitive", prompt)

        self.assertEqual(params["primitive_type"], "cube")
        self.assertEqual(params["name"], "TC_PROMPT_PROBE_cube")
        self.assertEqual(params["size"], 1.0)

    def test_maya_create_locator_beats_trailing_select_phrase(self):
        prompt = "In Maya, create a locator named prompt_smoke_locator and select it."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.create_locator")
        params = build_dcc_operation_params("maya", "scene.create_locator", prompt)

        self.assertEqual(params["name"], "prompt_smoke_locator")
        self.assertNotEqual(dcc_prompt_to_operation("maya", prompt), "scene.select")

    def test_maya_create_control_beats_trailing_select_and_parses_position(self):
        prompt = (
            "In Maya, if prompt_smoke_ctrl does not exist, create a nurbs circle control "
            "named prompt_smoke_ctrl, move it to X 1 Y 2 Z 3, and select it."
        )
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.create_control")
        params = build_dcc_operation_params("maya", "scene.create_control", prompt)

        self.assertEqual(params["name"], "prompt_smoke_ctrl")
        self.assertEqual(params["shape"], "circle")
        self.assertEqual(params["position"], [1.0, 2.0, 3.0])
        self.assertTrue(params["if_missing"])
        self.assertTrue(params["select"])
        self.assertNotEqual(dcc_prompt_to_operation("maya", prompt), "scene.select")

    def test_maya_generated_rig_control_move_requires_prerequisite_approval(self):
        prompt = "In Maya move pelvis_ctrl up 0.1 units on Y so I can verify the character control exists."
        self.assertEqual(dcc_prompt_to_operation("maya", prompt), "scene.move")
        params = build_dcc_operation_params("maya", "scene.move", prompt)
        self.assertEqual(params["objects"], ["pelvis_ctrl"])
        self.assertEqual(params["translation"], [0.0, 0.1, 0.0])

        decision = classify_prompt_route(prompt)
        self.assertEqual(decision.route, "action_graph")
        self.assertEqual(decision.intent_category, "maya_rigging_prerequisite_plan")
        self.assertTrue(decision.requires_confirmation)
        self.assertTrue(decision.requires_plan)
        self.assertIn("approval_to_create_hik_mapping_and_rig_if_missing", decision.missing_info)
        operation_ids = [operation["id"] for operation in decision.operations]
        self.assertEqual(
            operation_ids,
            [
                "verify_target_control",
                "requested_post_requisite_action",
                "verify_skeleton_origin",
                "create_hik_mapping_if_missing",
                "create_rig_if_missing",
                "verify_target_control_after_prerequisites",
                "requested_post_requisite_action_after_prerequisites",
            ],
        )
        self.assertEqual(decision.operations[0]["operation"], "scene.object_exists")
        self.assertEqual(decision.operations[0]["args"]["name"], "pelvis_ctrl")
        self.assertEqual(decision.operations[3]["operation"], "python.call")
        self.assertEqual(
            decision.operations[3]["callable"],
            "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
        )
        self.assertEqual(decision.operations[3]["args"]["root_joint"], "origin")
        self.assertEqual(decision.operations[3]["produces"], ["body_joint_map", "face_joint_map"])
        self.assertIn("setup_hik.py:create_rig_mapping", decision.operations[3]["evidence"][0])
        self.assertEqual(decision.operations[4]["operation"], "python.call")
        self.assertEqual(
            decision.operations[4]["callable"],
            "maya_tools.Rigging.create_rig.create_rig_from_mapping",
        )
        self.assertEqual(decision.operations[4]["args"]["body_joint_map"], "$body_joint_map")
        self.assertEqual(decision.operations[4]["args"]["face_joint_map"], "$face_joint_map")
        self.assertIn("create_rig.py:create_rig_from_mapping", decision.operations[4]["evidence"][0])
        self.assertEqual(decision.operations[1]["operation"], "scene.move")
        self.assertEqual(decision.operations[-1]["operation"], "scene.move")

    def test_maya_move_can_keep_object_selected(self):
        prompt = "In Maya, move prompt_smoke_locator up 2 units and keep it selected."
        params = build_dcc_operation_params("maya", "scene.move", prompt)
        self.assertEqual(params["objects"], ["prompt_smoke_locator"])
        self.assertEqual(params["translation"], [0.0, 2.0, 0.0])
        self.assertTrue(params["select_after"])

    def test_maya_generated_control_name_alone_triggers_prerequisite_plan(self):
        prompt = "Use the Omari file in Maya and move pelvis_ctrl up 0.1 units"

        decision = classify_prompt_route(prompt)

        self.assertEqual(decision.route, "action_graph")
        self.assertEqual(decision.intent_category, "maya_rigging_prerequisite_plan")
        self.assertEqual(decision.target_identifier, "scene.move")
        self.assertTrue(decision.requires_confirmation)
        self.assertEqual(decision.operations[0]["operation"], "scene.object_exists")
        self.assertEqual(decision.operations[0]["args"]["name"], "pelvis_ctrl")
        self.assertEqual(
            decision.operations[4]["callable"],
            "maya_tools.Rigging.create_rig.create_rig_from_mapping",
        )

    def test_maya_post_requisite_prompt_with_root_joint_context_still_routes_to_prerequisite_plan(self):
        prompt = (
            "Use the Omari file in Maya. Move pelvis_ctrl up 0.1 units. "
            "If pelvis_ctrl does not exist, do not create anything yet; "
            "report the prerequisite path you would take from the existing origin/root joint and ask for approval."
        )

        decision = classify_prompt_route(prompt)

        self.assertEqual(decision.route, "action_graph")
        self.assertEqual(decision.intent_category, "maya_rigging_prerequisite_plan")
        self.assertEqual(decision.target_identifier, "scene.move")
        self.assertIn("verify_skeleton_origin", [op["id"] for op in decision.operations])

    def test_maya_generated_rig_control_prerequisite_plan_survives_dispatch(self):
        context = RequestContext(
            text="In Maya move pelvis_ctrl up 0.1 units on Y so I can verify the character control exists.",
            project_roots=["C:/depot/tools"],
        )

        result = RequestEngine(progress=lambda _event: None, activity=lambda _event: None).process(context)

        self.assertEqual(result.action, "action_plan")
        plan = result.metadata["plan"]
        action_ids = [action["id"] for action in plan["actions"]]
        self.assertEqual(action_ids[0], "verify_target_control")
        self.assertEqual(plan["actions"][0]["args"]["operation"], "scene.object_exists")
        self.assertEqual(plan["actions"][1]["args"]["operation"], "scene.move")
        self.assertEqual(plan["actions"][3]["args"]["operation"], "python.call")
        self.assertEqual(
            plan["actions"][3]["args"]["callable"],
            "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
        )
        self.assertEqual(plan["actions"][3]["args"]["produces"], ["body_joint_map", "face_joint_map"])
        self.assertIn("setup_hik.py:create_rig_mapping", plan["actions"][3]["args"]["evidence"][0])
        self.assertTrue(plan["actions"][3]["requires_approval"])
        self.assertEqual(
            plan["actions"][4]["args"]["callable"],
            "maya_tools.Rigging.create_rig.create_rig_from_mapping",
        )
        self.assertEqual(plan["actions"][4]["args"]["params"]["body_joint_map"], "$body_joint_map")
        self.assertEqual(plan["actions"][4]["args"]["params"]["face_joint_map"], "$face_joint_map")
        self.assertEqual(plan["actions"][-1]["args"]["operation"], "scene.move")

    def test_maya_generated_rig_control_select_can_be_direct_when_user_says_existing_only(self):
        prompt = "In Maya just select existing pelvis_ctrl only if it already exists."
        params = build_dcc_operation_params("maya", "scene.select", prompt)
        self.assertEqual(params["objects"], ["pelvis_ctrl"])

        decision = classify_prompt_route(prompt)

        self.assertEqual(decision.route, "dcc_execute")
        self.assertEqual(decision.target_identifier, "scene.select")
        self.assertNotEqual(decision.intent_category, "maya_rigging_prerequisite_plan")

    def test_maya_joint_query_adapter_returns_first_joint(self):
        class FakeMayaBridge:
            def execute(self, code, timeout=60.0):
                return True, '{"first_joint": "root_JNT", "joints": ["root_JNT", "spine_JNT"], "count": 2}'

        class FakeRouter:
            maya = FakeMayaBridge()

        class FakeWindow:
            command_router = FakeRouter()

        decision = classify_prompt_route("In Maya what is the first bone name you can find?")
        context = RequestContext(text="In Maya what is the first bone name you can find?", extras={"window": FakeWindow()})
        request = build_dcc_execution_request(decision.to_dict(), context)
        result = default_dcc_execution_adapters()["maya"].query(request, context)

        self.assertEqual(result.status, "completed")
        self.assertIn("root_JNT", result.user_message)

    def test_maya_mutating_operation_checks_target_exists_before_execution(self):
        class FakeMayaBridge:
            def __init__(self):
                self.calls = []

            def execute(self, code, timeout=60.0):
                self.calls.append(code)
                if "cmds.objExists" in code:
                    return True, '{"missing": ["missing_ctrl"], "checked": ["missing_ctrl"]}'
                return True, "moved"

        class FakeRouter:
            maya = FakeMayaBridge()

        class FakeWindow:
            command_router = FakeRouter()

        prompt = "In Maya just select existing missing_ctrl only if it already exists."
        decision = classify_prompt_route(prompt)
        request = build_dcc_execution_request(decision.to_dict(), RequestContext(text=prompt))
        request.approved = True
        context = RequestContext(text=prompt, extras={"window": FakeWindow()})

        result = default_dcc_execution_adapters()["maya"].execute(request, context)

        self.assertEqual(result.status, "confirmation_required")
        self.assertIn("missing_ctrl", result.user_message)
        self.assertEqual(result.structured_data["missing_objects"], ["missing_ctrl"])

    def test_blender_create_cube_routes_to_execute(self):
        blender_decision = classify_prompt_route("Blender create cube named TestCube")
        self.assertEqual(blender_decision.route, "dcc_execute")
        self.assertEqual(blender_decision.host, "blender")
        self.assertEqual(blender_decision.target_identifier, "modeling.create_primitive")

    def test_houdini_has_execution_adapter(self):
        adapters = default_dcc_execution_adapters()

        self.assertIn("houdini", adapters)
        self.assertEqual(adapters["houdini"].query_methods["selection"], "direct_houdini_selection")


if __name__ == "__main__":
    unittest.main()
