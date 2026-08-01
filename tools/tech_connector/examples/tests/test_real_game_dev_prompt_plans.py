from __future__ import annotations

import unittest
import json
from pathlib import Path

from tech_connector.services.dcc.transfer_template_service import plan_transfer_permutation
from tech_connector.services.action_planner_service import plan_prompt_to_action_graph
from tech_connector.services.action_planner_service import workflow_plan_from_action_graph
from tech_connector.services.prompt.pipeline_prompt_flow_service import resolve_pipeline_prompt_flow
from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.unreal.anim_blueprint_capability_service import build_anim_blueprint_capability_plan
from tech_connector.services.unreal.feature_planning_service import _generic_unreal_feature_plan


class TestRealGameDevPromptPlans(unittest.TestCase):
    def _generic_unreal_plan(self, prompt: str) -> dict:
        return _generic_unreal_feature_plan(
            prompt,
            {
                "target_asset": "/Game/Characters/BP_Player",
                "blueprint": {
                    "parent_class": "Character",
                    "components": [],
                    "variables": [],
                    "functions": [],
                    "graphs": [{"name": "EventGraph"}],
                },
                "assets": {"related_animations": [], "related_blueprints": []},
                "animation_blueprints": [],
                "sufficient": False,
            },
        )

    def _step_by_domain(self, plan: dict, domain: str) -> dict:
        for step in plan.get("implementation_steps") or []:
            if step.get("domain") == domain:
                return step
        return {}

    def _goal_ids(self, decision):
        graph = decision.task_graph or {}
        goals = graph.get("ordered_goals") or graph.get("goals") or []
        return [goal.get("task_id") or goal.get("goal_id") for goal in goals]

    def _goal_by_id(self, decision, goal_id):
        graph = decision.task_graph or {}
        goals = graph.get("ordered_goals") or graph.get("goals") or []
        for goal in goals:
            if (goal.get("task_id") or goal.get("goal_id")) == goal_id:
                return goal
        return {}

    def test_unreal_stamina_feature_gets_dependency_ordered_code_plan(self) -> None:
        decision = classify_prompt_route(
            "In Unreal add a reusable stamina system for sprinting, dodging, and melee combos. "
            "It should drain while sprinting, block dodge when empty, regenerate after a delay, "
            "update the HUD, and compile the touched Blueprints.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("gameplay_feature_implementation", decision.intent_category)
        self.assertIn("gameplay_architecture", decision.required_context)
        self.assertEqual(
            [
                "inspect_gameplay_architecture",
                "resolve_feature_dependencies",
                "design_feature_plan",
                "implement_feature_changes",
                "validate_gameplay_feature",
            ],
            self._goal_ids(decision),
        )
        self.assertEqual(
            ["design_feature_plan"],
            self._goal_by_id(decision, "implement_feature_changes")["depends_on"],
        )

    def test_abp_crawl_feature_gets_capability_route_with_plan_graph(self) -> None:
        decision = classify_prompt_route(
            "Make a crawling locomotion system in ABP Combat for Manny: prone idle, "
            "crawl forward/back/strafe, transitions from crouch, input gating.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("unreal_capability", decision.route)
        self.assertEqual("unreal", decision.host)
        self.assertIn("animation_blueprint_context", decision.required_context)
        self.assertIn("design_feature_plan", self._goal_ids(decision))

    def test_maya_rigging_tool_gets_discovery_and_ui_dependency_fan_in(self) -> None:
        decision = classify_prompt_route(
            "Find existing Maya rigging functions and create a PySide tool to bind a mesh "
            "to selected joints, add/remove influences, validate selection, and add focused tests.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("dcc_tool_code_edit", decision.intent_category)
        design = self._goal_by_id(decision, "design_maya_tool")
        self.assertEqual(
            ["discover_maya_rigging_functions", "inspect_ui_patterns"],
            design["depends_on"],
        )
        self.assertEqual(["design_maya_tool"], self._goal_by_id(decision, "implement_maya_tool")["depends_on"])

    def test_read_only_graph_planner_review_stays_project_search_with_review_goals(self) -> None:
        decision = classify_prompt_route(
            "Review the Unreal graph mutation planner for performance risks, explain dependencies "
            "and likely hotspots, include line numbers, but do not edit files.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("project_search", decision.route)
        self.assertEqual("read_only", decision.mutation_scope)
        self.assertEqual(
            ["locate_review_targets", "trace_dependencies", "report_evidence"],
            self._goal_ids(decision),
        )

    def test_maya_to_unreal_animation_pipeline_has_producer_consumer_operations(self) -> None:
        decision = classify_prompt_route(
            "In Maya export selected Manny joints and animation to C:/tmp/manny_climb.fbx, "
            "then in Unreal import it into /Game/Characters/Manny/Animations and validate skeleton compatibility.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("pipeline_graph", decision.route)
        operations = decision.operations
        self.assertEqual(
            [
                "maya_validate_animation_export",
                "maya_export_selected_fbx",
                "unreal_import_fbx",
                "unreal_resolve_animation_target",
                "unreal_validate_imported_animation",
                "unreal_retarget_animation_if_needed",
                "unreal_report_animation_pipeline_assets",
            ],
            [operation["id"] for operation in operations],
        )
        self.assertEqual("$fbx_path", operations[2]["args"]["fbx_path"])
        self.assertEqual(
            "$target_skeleton_path",
            operations[4]["args"]["target_skeleton_path"],
        )
        self.assertEqual(
            "$compatibility_report",
            operations[5]["args"]["compatibility_report"],
        )
        self.assertIn("root-motion", " ".join(decision.deterministic_steps).lower())
        self.assertIn(
            "compatibility_report",
            [row["name"] for row in decision.expected_outcomes],
        )

    def test_blender_to_unreal_pipeline_does_not_collapse_to_single_dcc_operation(self) -> None:
        decision = classify_prompt_route(
            "Build a Blender to Unreal prop pipeline: clean selected mesh names, apply transforms, "
            "generate LOD0/LOD1, export FBX to C:/tmp/tc_prop.fbx, then import into Unreal "
            "/Game/Props/Test, create material slots, set collision, save assets, and produce validation output.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("pipeline_graph", decision.route)
        self.assertEqual("workflow_pipeline", decision.intent_category)
        self.assertNotEqual("material.create", decision.target_identifier)
        self.assertIn("workflow_graph", decision.required_context)

    def test_gameplay_word_does_not_steal_explicit_cross_dcc_pipeline(self) -> None:
        decision = classify_prompt_route(
            "Build a MotionBuilder to Blender to Unreal gameplay animation pipeline: "
            "export the current take, clean and bake it in Blender, import it into Unreal, "
            "retarget incompatible clips, create a BlendSpace, save, and report.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("pipeline_graph", decision.route)
        self.assertEqual("workflow_pipeline", decision.intent_category)
        self.assertNotEqual("gameplay_feature_implementation", decision.intent_category)

    def test_blender_to_unreal_prop_action_graph_has_concrete_host_steps(self) -> None:
        plan = plan_prompt_to_action_graph(
            "Build a Blender to Unreal prop pipeline: clean selected mesh names, apply transforms, "
            "generate LOD0/LOD1, export FBX to C:/tmp/tc_prop.fbx, then import into Unreal "
            "/Game/Props/Test, create material slots, set collision, save assets, and produce validation output.",
            ["C:/depot/tools"],
        )

        actions = plan.get("actions") or []
        self.assertEqual("dynamic_cross_dcc_pipeline", plan.get("intent"))
        self.assertEqual("dynamic_typed_pipeline_v1", plan.get("framework"))
        self.assertEqual(
            [
                "pipeline.process_meshes_for_transfer",
                "blender.export_fbx",
                "unreal_tools.asset_transfer_adapter.import_fbx_verified",
                "unreal_tools.asset_transfer_adapter.registry_readback",
            ],
            [action["args"]["operation"] for action in actions],
        )
        self.assertEqual("blender", actions[0]["args"]["host"])
        self.assertEqual("unreal", actions[2]["args"]["host"])
        self.assertEqual("$fbx_path", actions[2]["args"]["params"]["source_file"])
        self.assertEqual("$imported_paths", actions[3]["args"]["params"]["imported_paths"])
        self.assertEqual(1, actions[0]["args"]["params"]["lod_count"])
        self.assertTrue(actions[0]["args"]["params"]["create_collision"])
        self.assertEqual(["blender", "unreal"], plan.get("hosts"))

    def test_maya_blender_unreal_chain_preserves_all_hosts_and_data_edges(self) -> None:
        prompt = (
            "Create a Maya to Blender to Unreal validation pipeline: in Maya build a simple rigged animated proxy "
            "and export FBX to C:/tmp/tc_chain_maya.fbx, in Blender import it, clean mesh names, apply transforms, "
            "add material and collision proxy, export FBX to C:/tmp/tc_chain_blender.fbx, then in Unreal import it "
            "into /Game/AIStudio/Validation/Chain, save assets, and report registry readback."
        )
        decision = classify_prompt_route(prompt, project_roots=["C:/depot/tools"])
        plan = plan_prompt_to_action_graph(prompt, ["C:/depot/tools"])
        actions = plan.get("actions") or []

        self.assertEqual("pipeline_graph", decision.route)
        self.assertNotEqual("maya_export_selected_fbx", (decision.operations or [{}])[0].get("id"))
        self.assertEqual("dynamic_cross_dcc_pipeline", plan.get("intent"))
        self.assertEqual(
            [
                "pipeline.create_rigged_proxy",
                "animation.export",
                "io.import_fbx",
                "pipeline.process_meshes_for_transfer",
                "blender.export_fbx",
                "unreal_tools.asset_transfer_adapter.import_fbx_verified",
                "unreal_tools.asset_transfer_adapter.registry_readback",
            ],
            [action["args"]["operation"] for action in actions],
        )
        self.assertEqual(
            ["maya", "maya", "blender", "blender", "blender", "unreal", "unreal"],
            [action["args"]["host"] for action in actions],
        )
        self.assertEqual("$fbx_path", actions[2]["args"]["params"]["filepath"])
        self.assertEqual("$fbx_path", actions[5]["args"]["params"]["source_file"])
        self.assertEqual("$imported_paths", actions[6]["args"]["params"]["imported_paths"])
        self.assertEqual("C:/tmp/tc_chain_maya.fbx", actions[1]["args"]["params"]["export_path"])
        self.assertEqual("C:/tmp/tc_chain_blender.fbx", actions[4]["args"]["params"]["output_path"])
        self.assertEqual("/Game/AIStudio/Validation/Chain", actions[5]["args"]["params"]["destination_path"])
        self.assertTrue(plan.get("data_edges"))

    def test_official_ui_flow_materializes_cross_dcc_graph_and_runnable_code(self) -> None:
        prompt = (
            "Create a Maya to Blender to Unreal validation pipeline: in Maya build a simple rigged animated proxy "
            "and export FBX to C:/tmp/tc_chain_maya.fbx, in Blender import it, clean mesh names, apply transforms, "
            "add material and collision proxy, export FBX to C:/tmp/tc_chain_blender.fbx, then in Unreal import it "
            "into /Game/AIStudio/Validation/Chain, save assets, and report registry readback."
        )
        progress_events = []
        result = resolve_pipeline_prompt_flow(
            prompt,
            ["C:/depot/tools"],
            progress_callback=progress_events.append,
        )
        graph = result["action_graph"]
        workflow = result["workflow_plan"]

        self.assertTrue(result["ok"], result)
        self.assertEqual(prompt, result["original_prompt"])
        self.assertEqual("pipeline_graph", result["route_decision"]["route"])
        self.assertEqual(result["progress_events"], progress_events)
        self.assertEqual("REQUEST_RECEIVED", progress_events[0]["state"])
        self.assertEqual("READY", progress_events[-1]["state"])
        self.assertEqual("complete", progress_events[-1]["status"])
        self.assertTrue(any(event["state"] == "ACTION_PLANNING" for event in progress_events))
        self.assertTrue(any(event["state"] == "WORKFLOW_MATERIALIZATION" for event in progress_events))
        route_event = next(
            event
            for event in progress_events
            if event["state"] == "INTENT_CLASSIFIED" and event["status"] == "complete"
        )
        self.assertEqual("cross_dcc", route_event["details"]["host"])
        self.assertEqual(7, len(workflow["steps"]))
        self.assertEqual([], workflow["unresolved_inputs"])
        self.assertEqual(
            ["maya", "maya", "blender", "blender", "blender", "unreal", "unreal"],
            [step["symbol"]["host"] for step in workflow["steps"]],
        )
        self.assertEqual(
            [
                ("fbx_path", "filepath"),
                ("fbx_path", "source_file"),
                ("imported_paths", "imported_paths"),
            ],
            [
                (link["from_output"], link["to_input"])
                for link in workflow["data_links"]
            ],
        )
        self.assertEqual(6, len(workflow["flow_links"]))
        self.assertEqual(workflow, workflow_plan_from_action_graph(graph))

        class _PlanView:
            def ordered_step_data(self):
                return workflow["steps"]

            def manifest_data_links(self):
                return [
                    {
                        "from": f"step{link['from_step']}.{link['from_output']}",
                        "to": f"step{link['to_step']}.{link['to_input']}",
                    }
                    for link in workflow["data_links"]
                ]

            def manifest_flow_links(self):
                return [
                    {
                        "from": f"step{link['from_step']}.flow",
                        "to": f"step{link['to_step']}.flow",
                    }
                    for link in workflow["flow_links"]
                ]

        code = generate_pipeline_code_from_graph(
            "maya_blender_unreal_validation",
            prompt,
            workflow["steps"],
            view=_PlanView(),
        )
        compile(code, "<official-ui-cross-dcc-pipeline>", "exec")
        self.assertIn("execute_pipeline_operation", code)
        self.assertIn("maya_tools.Rigging.validation_proxy.create_rigged_proxy", code)
        self.assertIn("blender_tools.pipeline_transfer.process_meshes_for_transfer", code)
        self.assertIn("unreal_tools.asset_transfer_adapter.import_fbx_verified", code)
        self.assertIn("outputs['step2']['fbx_path']", code)
        self.assertIn("outputs['step5']['fbx_path']", code)
        self.assertIn("outputs['step6']['imported_paths']", code)
        self.assertIn("import time", code)
        self.assertIn("'elapsed_ms': round(", code)
        self.assertIn("'rollback':", code)
        self.assertIn("[Pipeline 1/7] START MAYA", code)
        self.assertIn("[Pipeline 7/7] COMPLETE UNREAL", code)
        self.assertIn("[Pipeline] COMPLETE: 7 stage(s) succeeded", code)
        imported_paths_contract = next(
            item
            for item in workflow["steps"][6]["symbol"]["params"]
            if item["name"] == "imported_paths"
        )
        self.assertEqual("list[str]", imported_paths_contract["annotation"])

    def test_transfer_template_registry_enumerates_cross_dcc_permutations(self) -> None:
        chain = plan_transfer_permutation(
            "Maya export rigged animation FBX, Blender import and clean it, export FBX, then Unreal import and read back assets."
        )
        prop = plan_transfer_permutation(
            "Blender to Unreal prop pipeline: export FBX static mesh, import to Unreal, save and validate."
        )

        self.assertTrue(chain["success"], chain)
        self.assertEqual(["maya", "blender", "unreal"], chain["hosts"])
        self.assertEqual(
            [
                "maya.operations.animation.export",
                "blender.operations.io.import_fbx",
                "blender.operations.blender.clean_animation",
                "blender.operations.blender.export_fbx",
                "unreal.unreal_tools_functions.unreal_tools.asset_transfer_adapter.import_fbx_verified",
                "unreal.unreal_tools_functions.unreal_tools.asset_transfer_adapter.registry_readback",
            ],
            [step["key"] for step in chain["steps"]],
        )
        self.assertTrue(prop["success"], prop)
        self.assertEqual("static_mesh", prop["subject"])
        self.assertEqual(
            [
                "blender.operations.blender.export_fbx",
                "unreal.unreal_tools_functions.unreal_tools.asset_transfer_adapter.import_fbx_verified",
                "unreal.unreal_tools_functions.unreal_tools.asset_transfer_adapter.registry_readback",
            ],
            [step["key"] for step in prop["steps"]],
        )

    def test_abp_gap_wrapper_plans_include_ui_progress_phases(self) -> None:
        plan = build_anim_blueprint_capability_plan(
            "In ABP Combat add Manny crawl locomotion: resolve the AnimBlueprint, add states, wire transitions, compile."
        )

        wrappers = plan["cpp_wrapper_plans"]
        self.assertTrue(wrappers)
        for wrapper in wrappers:
            if wrapper.get("requires_known_implementation_strategy") and not wrapper.get("known_strategy"):
                self.assertEqual(
                    "Blocked wrapper generation because this operation has no declared implementation strategy.",
                    wrapper["message"],
                )
                self.assertIn("required_before_codegen", wrapper)
                continue
            phases = wrapper["progress_phases"]
            self.assertEqual(
                [
                    "prepare_plugin_source",
                    "write_plugin_files",
                    "build_cpp_plugin",
                    "enable_plugin",
                    "restart_unreal_if_needed",
                    "validate_reflected_python_call",
                    "register_validated_capability",
                ],
                [phase["id"] for phase in phases],
            )
            self.assertEqual([5, 20, 45, 60, 75, 90, 100], [phase["percent"] for phase in phases])
            self.assertTrue(all(phase["label"] for phase in phases))

    def test_abp_plugin_entries_are_not_reported_as_missing_generics(self) -> None:
        plan = build_anim_blueprint_capability_plan(
            "In ABP Combat add Manny crawl locomotion: inspect graph, add states, "
            "add transitions when bWantsToCrawl && CrawlInputVector.X > 0.1, compile and save."
        )

        available = {cap["operation"]: cap for cap in plan["available_capabilities"]}
        gaps = {gap["operation"]: gap for gap in plan["capability_gaps"]}
        wrappers = {wrapper["operation"]: wrapper for wrapper in plan["cpp_wrapper_plans"]}
        preflight = plan["execution_preflight"]

        self.assertEqual("available", available["blueprint.scan"]["status"])
        self.assertEqual(
            "plugin_body_present_live_validation_pending",
            available["blueprint.compile_and_save"]["status"],
        )
        self.assertNotIn("blueprint.scan", gaps)
        self.assertNotIn("blueprint.compile_and_save", gaps)
        self.assertNotIn("anim_graph.add_state", gaps)
        self.assertNotIn("anim_graph.add_transition_rule", gaps)
        self.assertNotIn("anim_graph.synthesize_transition_rule_expression", gaps)
        self.assertNotIn("anim_graph.wire_state_machine_to_output_pose", gaps)
        self.assertEqual(
            "plugin_body_present_build_validated_live_asset_validation_pending",
            available["anim_graph.add_state"]["status"],
        )
        self.assertEqual(
            "plugin_body_present_constant_rules_supported_complex_rules_use_synthesis_live_asset_validation_pending",
            available["anim_graph.add_transition_rule"]["status"],
        )
        self.assertEqual(
            "plugin_body_present_bounded_boolean_expression_synthesis_live_asset_validation_pending",
            available["anim_graph.synthesize_transition_rule_expression"]["status"],
        )
        self.assertFalse(wrappers["anim_graph.add_state"]["is_execution_blocker"])
        self.assertFalse(wrappers["anim_graph.synthesize_transition_rule_expression"]["is_execution_blocker"])
        self.assertTrue(wrappers["anim_graph.synthesize_transition_rule_expression"]["ok"])
        self.assertTrue(preflight["ready_for_direct_execution"])
        self.assertEqual([], preflight["blockers"])
        self.assertFalse(wrappers["blueprint.scan"]["is_execution_blocker"])

    def test_ai_studio_bridge_manifest_maps_operation_aliases(self) -> None:
        manifest_path = Path("plugins/AIStudioBridge/AIStudioBridgeCapabilities.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        aliases = {
            capability["name"]: set(capability.get("operation_aliases") or [])
            for capability in manifest["capabilities"]
        }

        self.assertIn("blueprint.scan", aliases["inspect_anim_blueprint_graph"])
        self.assertIn("anim_graph.add_state", aliases["add_anim_graph_state"])
        self.assertIn("anim_graph.add_transition_rule", aliases["add_anim_graph_transition_rule"])
        self.assertIn("animation.delete_state", aliases["delete_anim_graph_state"])
        self.assertIn("animation.delete_transition", aliases["delete_anim_graph_transition"])
        self.assertIn("animation.rename_state", aliases["rename_anim_graph_state"])
        self.assertIn("animation.set_state_transition_rule", aliases["set_anim_graph_transition_rule"])
        self.assertIn(
            "anim_graph.synthesize_transition_rule_expression",
            aliases["synthesize_anim_graph_transition_rule_expression"],
        )
        self.assertIn("anim_graph.wire_state_machine_to_output_pose", aliases["wire_anim_graph_output_pose"])
        self.assertIn("blueprint.compile_and_save", aliases["compile_and_save_anim_blueprint"])

    def test_blueprint_graph_mutation_plan_includes_transaction_and_preservation_steps(self) -> None:
        plan = self._generic_unreal_plan(
            "In Unreal mutate BP_Player EventGraph: add an authority Branch before ApplyDamage, "
            "wire execution pins, create any needed variable, compile, rescan, and prove no unrelated nodes moved."
        )

        step = self._step_by_domain(plan, "blueprint_graph_mutation")
        self.assertTrue(step, plan.get("detected_domains"))
        self.assertEqual(
            [
                "blueprint.scan",
                "blueprint.search_node_actions",
                "blueprint.describe_node_action",
                "blueprint.probe_node_action",
                "blueprint.apply_graph_spec",
                "blueprint.compile",
                "blueprint.get_compile_errors",
                "blueprint.scan",
            ],
            step["operations"],
        )
        self.assertIn("unrelated nodes", step["detail"])

    def test_replication_feature_plan_requires_authority_and_multiplayer_validation(self) -> None:
        plan = self._generic_unreal_plan(
            "In Unreal implement replicated ammo and reload: server authority, client request RPC, "
            "replicated ammo variable, OnRep HUD update, prediction notes, and two-client PIE validation."
        )

        step = self._step_by_domain(plan, "networking")
        self.assertTrue(step, plan.get("detected_domains"))
        self.assertEqual(
            [
                "blueprint.configure_replication",
                "network.inspect_authority_flow",
                "runtime.multiplayer_pie_validate",
            ],
            step["operations"],
        )
        self.assertIn("two PIE clients", step["detail"])

    def test_compound_unreal_feature_preserves_every_clause_and_expands_concrete_operations(self) -> None:
        prompt = (
            "In Unreal 5.8, inspect the played character and implement a network-ready traversal "
            "and presentation stack: Enhanced Input actions and mappings for sprint, crouch, prone, "
            "crawl, mantle, and dodge; replicated stamina with server authority, RepNotify, and HUD "
            "updates; Motion Matching with Pose Search; IK Rig and IK Retargeter compatibility proof; "
            "extend the current AnimBlueprint with locomotion states and concrete transition rules for "
            "crouch, prone, crawl, mantle, and dodge; preserve additive slots and root motion through "
            "Output Pose; create PhysicsAsset constraint and physical-animation profiles; create an "
            "editable Niagara character aura and landing burst attached only to a validated skeleton "
            "bone, bind Blueprint variables to Niagara user parameters, and replicate the visible state. "
            "Record rollback snapshots, compile and save every touched asset, read diagnostics, run "
            "two-client PIE validation, and report every asset path, operation, function, argument, "
            "dependency, and readback result."
        )
        plan = self._generic_unreal_plan(prompt)
        domains = set(plan.get("detected_domains") or [])

        self.assertTrue(plan["prompt_clause_coverage"]["complete"])
        self.assertEqual(9, plan["prompt_clause_coverage"]["covered_clause_count"])
        self.assertGreaterEqual(
            plan["detailed_implementation_plan"]["readiness"]["action_count"],
            20,
        )
        self.assertEqual([], plan["missing_capabilities"])
        self.assertTrue(
            {
                "enhanced_input",
                "stamina",
                "stamina_replication",
                "motion_matching",
                "ik_retarget",
                "anim_graph_state_machine",
                "animation_pose_path",
                "physics_profiles",
                "niagara",
                "networking",
                "rollback",
                "validation",
                "reporting",
            }.issubset(domains)
        )

        anim_step = self._step_by_domain(plan, "anim_graph_state_machine")
        self.assertEqual(5, anim_step["operations"].count("anim_graph.add_state"))
        self.assertEqual(5, anim_step["operations"].count("anim_graph.add_transition_rule"))
        self.assertIn("anim_graph.wire_state_machine_to_output_pose", anim_step["operations"])
        self.assertIn("blueprint.compile_and_save", anim_step["operations"])

        network_step = self._step_by_domain(plan, "networking")
        network_args = network_step["operation_arguments"]
        self.assertEqual(
            ["Stamina"],
            network_args["blueprint.configure_replication"]["rep_notify_variables"],
        )
        self.assertEqual(
            ["OnRep_Stamina"],
            network_args["network.inspect_authority_flow"]["required_onrep_functions"],
        )
        self.assertNotIn("InventoryEntries", json.dumps(network_args))

        validation_step = self._step_by_domain(plan, "validation")
        self.assertIn("asset.save", validation_step["operations"])
        self.assertEqual("$each_touched_asset", validation_step["operation_arguments"]["asset.save"]["asset_path"])

    def test_networked_inventory_route_exposes_full_callable_contract_before_discovery(self) -> None:
        prompt = (
            "In Unreal implement a networked pickup and inventory flow: overlap detection, "
            "server authority, client request RPC, replicated inventory array, OnRep HUD notification, "
            "save/load hook, rollback journal, and two-client PIE validation."
        )
        decision = classify_prompt_route(prompt, project_roots=["C:/depot/tools"])
        operations = decision.operations
        operation_names = [row["operation"] for row in operations]

        self.assertEqual("target_discovery", decision.route)
        self.assertIn("blueprint.configure_replication", operation_names)
        self.assertIn("network.inspect_authority_flow", operation_names)
        self.assertIn("runtime.multiplayer_pie_validate", operation_names)
        self.assertIn("rollback.record_asset_snapshot", operation_names)
        self.assertNotIn("ui.create_widget", operation_names)
        self.assertNotIn("savegame.create_schema", operation_names)
        self.assertEqual([], decision.task_graph["missing_operations"])

        configure = next(
            row for row in operations
            if row["operation"] == "blueprint.configure_replication"
        )
        self.assertEqual(
            ["InventoryEntries"],
            configure["planned_arguments"]["rep_notify_variables"],
        )
        self.assertEqual(
            ["Server_RequestPickup"],
            configure["planned_arguments"]["server_rpc_functions"],
        )

    def test_data_driven_pickup_plan_names_schema_lookup_and_save_contract(self) -> None:
        plan = self._generic_unreal_plan(
            "In Unreal make item pickups driven by a DataAsset/DataTable schema with rarity, "
            "stack size, icon, save/load persistence, and runtime lookup validation."
        )

        step = self._step_by_domain(plan, "data_driven_gameplay")
        self.assertTrue(step, plan.get("detected_domains"))
        self.assertIn("dataasset.create_or_update", step["operations"])
        self.assertIn("datatable.create_or_update", step["operations"])
        self.assertIn("blueprint.bind_data_lookup", step["operations"])
        self.assertIn("save/load stores identifiers", step["detail"])

    def test_ai_behavior_plan_requires_blackboard_perception_and_runtime_validation(self) -> None:
        plan = self._generic_unreal_plan(
            "In Unreal add enemy AI patrol and perception behavior: patrol spline, sight/hearing stimulus, "
            "chase state, lose target timeout, blackboard keys, behavior tree tasks, and debug draw validation."
        )

        ai_steps = [step for step in plan.get("implementation_steps") or [] if step.get("domain") == "ai_behavior"]
        self.assertEqual(2, len(ai_steps), plan.get("implementation_steps"))
        self.assertIn("ai.inspect_behavior_tree", ai_steps[0]["operations"])
        self.assertIn("ai.author_behavior", ai_steps[1]["operations"])
        self.assertIn("runtime.ai_validate", ai_steps[1]["operations"])
        self.assertIn("blackboard", ai_steps[0]["detail"])


if __name__ == "__main__":
    unittest.main()
