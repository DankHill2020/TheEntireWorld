import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reasoning_runtime.engine.progress_events import ActivityEvent, EngineResult, ProgressEvent
from tech_connector.services.api_feature_registry_service import APIFeatureDescriptor
from tech_connector.api import (
    API_VERSION,
    TechConnectorHeadlessAPI,
    call_function,
    execute_prompt_chain,
    plan_prompt_chain,
    reasoning_capabilities,
    run_reasoning,
    verify_license,
)
from tech_connector.services.license_entitlement_service import make_license_token


class HeadlessAPITests(unittest.TestCase):
    def setUp(self):
        self.legacy_environment = patch.dict(
            "os.environ",
            {"TECH_CONNECTOR_ALLOW_LEGACY_ENTITLEMENT": "1"},
        )
        self.legacy_environment.start()

    def tearDown(self):
        self.legacy_environment.stop()

    def _settings(self, secret: str, tier: str = "personal") -> dict:
        return {
            "tech_connector_require_login": True,
            "tech_connector_license_token": make_license_token(
                {"email": "creator@example.com", "tier": tier, "license_id": f"lic_{tier}"},
                secret,
            ),
        }

    def test_verify_license_does_not_require_ui(self):
        secret = "api-secret"
        status = verify_license(self._settings(secret), license_secret=secret)

        self.assertTrue(status["connected"])
        self.assertEqual("personal", status["tier"])
        self.assertIn("official_api_access", status["capabilities"])

    def test_call_function_through_official_api_without_ui(self):
        secret = "api-secret"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sample_tool.py").write_text(
                "def add_values(a, b=0):\n"
                "    return a + b\n",
                encoding="utf-8",
            )
            api = TechConnectorHeadlessAPI(
                settings=self._settings(secret),
                project_root=root,
                license_secret=secret,
            )

            result = api.call_function(
                "sample_tool.add_values",
                3,
                kwargs={"b": 4},
                extra_roots=[str(root)],
                stamp_project_provenance=True,
            )

            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(7, result.result["value"])
            self.assertEqual("sample_tool.add_values", result.result["entry_point"])
            self.assertEqual("personal", result.provenance["license_tier"])
            self.assertTrue((root / ".tech_connector" / "provenance.json").exists())

    def test_module_level_call_function_helper(self):
        secret = "api-secret"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sample_label_tool.py").write_text(
                "def label(value):\n"
                "    return f'label:{value}'\n",
                encoding="utf-8",
            )

            result = call_function(
                "sample_label_tool.label",
                "asset",
                settings=self._settings(secret),
                project_root=root,
                license_secret=secret,
                extra_roots=[str(root)],
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("label:asset", result.result["value"])

    def test_locked_license_blocks_api_call(self):
        api = TechConnectorHeadlessAPI(settings={"tech_connector_require_login": True})

        result = api.call_function("missing.module.fn")

        self.assertFalse(result.ok)
        self.assertIn("license", result.error.lower())

    def test_offline_community_mode_does_not_unlock_programmatic_api(self):
        api = TechConnectorHeadlessAPI(
            settings={
                "tech_connector_require_login": True,
                "tech_connector_allow_offline_community": True,
            }
        )

        result = api.call_function("missing.module.fn")

        self.assertFalse(result.ok)
        self.assertIn("official api access", result.error.lower())

    def test_plan_prompt_returns_action_graph_without_ui(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(settings=self._settings(secret), license_secret=secret)

        graph = api.plan_prompt("Find function add_values()")

        self.assertTrue(graph["actions"])
        self.assertIn(graph["intent"], {"symbol_search", "project_search"})

    def test_reasoning_capabilities_expose_shared_runtime(self):
        secret = "api-secret"
        settings = self._settings(secret)

        capabilities = reasoning_capabilities(
            settings=settings,
            license_secret=secret,
        )

        self.assertEqual(API_VERSION, capabilities["api_version"])
        self.assertIn("reasoning.runtime", capabilities["features"])
        runtime_feature = next(
            feature
            for feature in capabilities["feature_manifest"]["features"]
            if feature["feature_id"] == "reasoning.runtime"
        )
        self.assertIn("run", runtime_feature["operations"])
        self.assertEqual("direct", runtime_feature["access"])
        self.assertEqual("orchestration", runtime_feature["lifecycle_stage"])
        self.assertGreaterEqual(capabilities["adapter_counts"]["context"], 1)
        self.assertGreaterEqual(capabilities["adapter_counts"]["validation"], 1)

    def test_feature_manifest_describes_full_tech_connector_lifecycle(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
        )

        manifest = api.features.manifest()
        features = {
            feature["feature_id"]: feature
            for feature in manifest["features"]
        }

        self.assertEqual("tech_connector.api_features.v2", manifest["schema"])
        self.assertEqual(
            "direct",
            features["understanding.request_frame"]["access"],
        )
        self.assertEqual(
            "code.project_edit_workflow",
            features["repair.symbol_chunks"]["owner_feature_id"],
        )
        self.assertEqual(
            "internal",
            features["ui.pipeline_node_graph"]["access"],
        )
        self.assertEqual(
            "reasoning.runtime",
            features["models.provider_routing"]["owner_feature_id"],
        )

    def test_direct_lifecycle_feature_is_invokable(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
        )

        result = api.features.invoke(
            "understanding.request_frame",
            "analyze",
            prompt="Create a Maya exporter and Unreal importer.",
        )

        self.assertTrue(result.ok, result.to_dict())
        self.assertIsInstance(result.result["value"], dict)

    def test_feature_registry_discovers_and_invokes_runtime_adapter_granularly(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            project_root=".",
            license_secret=secret,
        )

        context_features = api.features.list(category="runtime.context")
        context_feature = next(
            feature
            for feature in context_features
            if feature["feature_id"].endswith("tech_connector_context")
        )
        result = api.features.invoke(
            context_feature["feature_id"],
            "active_context",
        )

        self.assertTrue(result.ok, result.to_dict())
        self.assertIn("project_root", result.result["value"])
        self.assertEqual(
            "tech_connector.adapters.dcc_context_adapter.DccContextAdapter",
            context_feature["source"],
        )

    def test_external_feature_can_register_without_editing_public_api(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
        )
        descriptor = APIFeatureDescriptor(
            feature_id="custom.example",
            category="custom",
            version="1.0",
            description="Example extension.",
            lifecycle_stage="studio_review",
            operations=("echo",),
            source="test.extension",
        )
        api.features.register(
            descriptor,
            {"echo": lambda value="": {"echo": value}},
        )

        discovered = api.features.get("custom.example")
        result = api.features.invoke("custom.example", "echo", value="hello")

        self.assertEqual("test.extension", discovered["source"])
        self.assertEqual("direct", discovered["access"])
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual({"echo": "hello"}, result.result["value"])

    def test_external_feature_can_be_replaced_in_one_api_instance(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
        )
        descriptor = APIFeatureDescriptor(
            feature_id="custom.replaceable",
            category="custom",
            version="1.0",
            description="Replaceable example.",
            operations=("value",),
        )
        api.features.register(descriptor, {"value": lambda: "v1"})
        api.features.register(
            APIFeatureDescriptor(
                feature_id="custom.replaceable",
                category="custom",
                version="2.0",
                description="Replacement example.",
                operations=("value",),
            ),
            {"value": lambda: "v2"},
            replace=True,
        )

        result = api.features.invoke("custom.replaceable", "value")

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("v2", result.result["value"])
        self.assertEqual("2.0", api.features.get("custom.replaceable")["version"])

    def test_runtime_package_extends_context_and_feature_manifest(self):
        class StudioContext:
            """Supply test studio context."""

            name = "studio_publish"

            def get_active_context(self):
                return {"asset_id": "character.hero"}

            def get_interaction_surface(self):
                from reasoning_runtime.adapters.context_adapter import InteractionSurface

                return InteractionSurface(kind="asset_publish_dashboard")

            def get_permission_context(self):
                return {"can_publish": False}

        class StudioPackage:
            def get_context_adapters(self):
                return [StudioContext()]

        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            runtime_packages=[StudioPackage()],
        )

        snapshot = api.reasoning.snapshot("Inspect publish state.")
        feature = api.features.get("runtime.context.studio_publish")

        self.assertTrue(snapshot.ok, snapshot.to_dict())
        self.assertEqual(
            "character.hero",
            snapshot.result["runtime"]["context"]["studio_publish"]["asset_id"],
        )
        self.assertEqual("direct", feature["access"])
        self.assertIn("active_context", feature["operations"])

    def test_reasoning_snapshot_uses_project_aware_domain_package(self):
        secret = "api-secret"
        with tempfile.TemporaryDirectory() as temp_dir:
            api = TechConnectorHeadlessAPI(
                settings=self._settings(secret),
                project_root=temp_dir,
                license_secret=secret,
            )

            snapshot = api.reasoning.snapshot("Inspect the active project")

        self.assertTrue(snapshot.ok, snapshot.to_dict())
        runtime = snapshot.result["runtime"]
        self.assertEqual(
            str(Path(temp_dir).resolve()),
            runtime["context"]["tech_connector_context"]["project_root"],
        )
        self.assertTrue(runtime["tools"])
        self.assertTrue(runtime["rule_sets"])

    def test_reasoning_context_accepts_api_neutral_surface_aliases(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
        )

        prepared = api.reasoning.prepare(
            "Review this publish request.",
            context={
                "interaction_surface": "asset_publish_dashboard",
                "asset_id": "character.hero",
            },
        )
        default_context = api.reasoning.prepare("Explain the registry.")

        self.assertTrue(prepared.ok, prepared.to_dict())
        self.assertEqual(
            "asset_publish_dashboard",
            prepared.result["context"]["active_tab"],
        )
        self.assertEqual(
            "character.hero",
            prepared.result["context"]["extras"]["asset_id"],
        )
        self.assertTrue(default_context.ok, default_context.to_dict())
        self.assertEqual("API", default_context.result["context"]["active_tab"])

    def test_run_reasoning_serializes_events_and_sanitizes_thread_context(self):
        secret = "api-secret"
        observed = {}

        class FakeRequestEngine:
            def __init__(self, progress=None, activity=None, runtime_kernel=None, **_kwargs):
                self.progress = progress
                self.activity = activity
                self.runtime_kernel = runtime_kernel

            def process(self, context):
                observed["context"] = context
                self.progress(ProgressEvent("reasoning", "Prepared", 1, 2, "safe"))
                self.activity(ActivityEvent("reasoning", "Runtime", status="ok"))
                return EngineResult(
                    action="answer",
                    label="Reasoning",
                    text="shared-runtime-result",
                    metadata={
                        "result_type": "answer",
                        "reasoning_runtime": {"ok": True},
                    },
                )

        callback_events = []
        with patch("tech_connector.engine.request_engine.RequestEngine", FakeRequestEngine):
            result = run_reasoning(
                "Explain the current implementation",
                settings=self._settings(secret),
                license_secret=secret,
                context={
                    "thread": [{"role": "user", "content": "Keep the full context."}],
                    "extras": {"api_key": "remove-me", "safe": "keep-me"},
                },
                progress_callback=callback_events.append,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("shared-runtime-result", result.result["response"]["text"])
        self.assertEqual(1, result.result["progress"][0]["current"])
        self.assertEqual(2, result.result["progress"][0]["total"])
        self.assertEqual(result.result["progress"], callback_events)
        self.assertNotIn("api_key", observed["context"].extras)
        self.assertEqual("keep-me", observed["context"].extras["safe"])
        self.assertEqual(
            "Keep the full context.",
            observed["context"].extras["conversation_history"][0]["content"],
        )

    def test_runtime_tools_are_discoverable_and_mutation_requires_approval(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
        )

        tools = api.reasoning.tools()
        self.assertTrue(tools.ok, tools.to_dict())
        mutable = next(
            tool
            for tool in tools.result["tools"]
            if tool["mutability"] != "read_only"
        )
        blocked = api.reasoning.execute_tool(mutable["name"], {})
        preview = api.reasoning.execute_tool(mutable["name"], {}, dry_run=True)

        self.assertFalse(blocked.ok)
        self.assertIn("approved=True", blocked.error)
        self.assertTrue(preview.ok, preview.to_dict())
        self.assertFalse(preview.result["executed"])

    def test_plan_prompt_chain_returns_understanding_for_each_step_without_ui(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(settings=self._settings(secret), license_secret=secret)

        chain = api.plan_prompt_chain(
            [
                "Find function add_values()",
                "Find function export_fbx()",
            ]
        )

        self.assertTrue(chain["ok"])
        self.assertEqual(2, chain["step_count"])
        self.assertEqual("Find function add_values()", chain["steps"][0]["prompt"])
        self.assertTrue(chain["steps"][0]["graph"]["actions"])
        self.assertIn("understanding", chain["steps"][0])

    def test_module_prompt_chain_helpers_do_not_require_ui(self):
        secret = "api-secret"
        settings = self._settings(secret)

        planned = plan_prompt_chain(
            "Find function add_values() then Find function export_fbx()",
            settings=settings,
            license_secret=secret,
        )
        executed = execute_prompt_chain(
            ["Find function add_values()", "Find function export_fbx()"],
            settings=settings,
            license_secret=secret,
            dry_run=True,
        )

        self.assertEqual(2, planned["step_count"])
        self.assertTrue(executed.ok, executed.to_dict())
        self.assertEqual(2, executed.result["completed_steps"])
        self.assertEqual("dry_run", executed.result["steps"][0]["execution"]["status"])

    def test_call_dcc_function_auto_routes_through_router_without_ui(self):
        secret = "api-secret"

        class FakeRouter:
            def host_for_tool_function(self, entry_point):
                return "maya" if entry_point.startswith("maya_tools.") else ""

            def execute_tool_function_from_text(self, text):
                self.payload = text
                return "Maya Function", True, "dcc-result"

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.call_dcc_function("maya_tools.Rigging.foo.build", kwargs={"name": "root"})

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("dcc-result", result.result["output"])
        self.assertEqual("maya", result.result["host"])
        self.assertEqual("personal", result.provenance["license_tier"])

    def test_call_dcc_function_explicit_maya_host_uses_bridge_call_function(self):
        secret = "api-secret"

        class FakeBridge:
            def call_function(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "maya-bridge-result"

        class FakeRouter:
            def __init__(self):
                self.bridge = FakeBridge()

            def _host_bridge_for_operation(self, host):
                return self.bridge if host == "maya" else None

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.call_dcc_function("custom_maya_package.make_locator", "LOC_API", host="maya")

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("maya-bridge-result", result.result["output"])
        self.assertEqual(("custom_maya_package.make_locator", ["LOC_API"], {}), router.bridge.called)

    def test_call_dcc_function_explicit_unreal_host_uses_unreal_call(self):
        secret = "api-secret"

        class FakeUnreal:
            def call(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "unreal-result"

        class FakeRouter:
            unreal = FakeUnreal()

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.call_dcc_function("unreal_tools.assets.find_assets", host="unreal", kwargs={"type": "Blueprint"})

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("unreal-result", result.result["output"])
        self.assertEqual(("unreal_tools.assets.find_assets", [], {"type": "Blueprint"}), router.unreal.called)

    def test_call_dcc_function_locked_license_blocks_before_bridge(self):
        class FakeRouter:
            def execute_tool_function_from_text(self, _text):
                raise AssertionError("should not execute without entitlement")

        api = TechConnectorHeadlessAPI(settings={"tech_connector_require_login": True}, command_router=FakeRouter())

        result = api.call_dcc_function("maya_tools.Rigging.foo.build", host="maya")

        self.assertFalse(result.ok)
        self.assertIn("license", result.error.lower())

    def test_dcc_namespace_unreal_alias_calls_official_entry_point(self):
        secret = "api-secret"

        class FakeUnreal:
            def call(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "asset-result"

        class FakeRouter:
            unreal = FakeUnreal()

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.dcc.unreal.find_assets("BP_Player", expected_class="Blueprint")

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("asset-result", result.result["output"])
        self.assertEqual(
            ("unreal_tools.assets.find_asset_path_by_name", ["BP_Player"], {"expected_class": "Blueprint"}),
            router.unreal.called,
        )

    def test_call_dcc_function_namespace_supports_host_aliases(self):
        secret = "api-secret"

        class FakeUnreal:
            def call(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "asset-result"

        class FakeRouter:
            unreal = FakeUnreal()

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.call_dcc_function.unreal.find_assets("BP_Player", expected_class="Blueprint")

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            ("unreal_tools.assets.find_asset_path_by_name", ["BP_Player"], {"expected_class": "Blueprint"}),
            router.unreal.called,
        )

    def test_dcc_namespace_maya_create_rig_alias_stays_on_bridge_stack(self):
        secret = "api-secret"

        class FakeBridge:
            def call_function(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "rig-result"

        class FakeRouter:
            def __init__(self):
                self.bridge = FakeBridge()

            def _host_bridge_for_operation(self, host):
                return self.bridge if host == "maya" else None

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.dcc.maya.create_rig(body_joint_map={"root": "origin"}, face_joint_map={})

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("rig-result", result.result["output"])
        self.assertEqual(
            (
                "maya_tools.Rigging.create_rig.create_rig_from_mapping",
                [],
                {"body_joint_map": {"root": "origin"}, "face_joint_map": {}},
            ),
            router.bridge.called,
        )

    def test_dcc_namespace_can_call_explicit_full_path_without_alias(self):
        secret = "api-secret"

        class FakeBridge:
            def call_function(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "custom-result"

        class FakeRouter:
            def __init__(self):
                self.bridge = FakeBridge()

            def _host_bridge_for_operation(self, host):
                return self.bridge if host == "maya" else None

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.dcc.maya.call("custom_tools.rig.cleanup", kwargs={"delete_unused": True})

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(("custom_tools.rig.cleanup", [], {"delete_unused": True}), router.bridge.called)

    def test_dcc_namespace_resolves_unique_catalog_function_name(self):
        secret = "api-secret"

        class FakeBridge:
            def call_function(self, entry_point, args=None, kwargs=None):
                self.called = (entry_point, args, kwargs)
                return True, "aim-result"

        class FakeRouter:
            def __init__(self):
                self.bridge = FakeBridge()

            def _host_bridge_for_operation(self, host):
                return self.bridge if host == "maya" else None

        router = FakeRouter()
        api = TechConnectorHeadlessAPI(
            settings=self._settings(secret),
            license_secret=secret,
            command_router=router,
        )

        result = api.dcc.maya.aim_joint_x_axis_to_world_x("joint1")

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            ("maya_tools.Rigging.mocap.setup_hik.aim_joint_x_axis_to_world_x", ["joint1"], {}),
            router.bridge.called,
        )

    def test_dcc_namespace_lists_current_official_aliases(self):
        secret = "api-secret"
        api = TechConnectorHeadlessAPI(settings=self._settings(secret), license_secret=secret)

        aliases = api.dcc.aliases()

        self.assertEqual(
            "maya_tools.Rigging.create_rig.create_rig_from_mapping",
            aliases["maya"]["create_rig"],
        )
        self.assertEqual(
            "unreal_tools.assets.find_asset_path_by_name",
            aliases["unreal"]["find_assets"],
        )

    def test_api_catalog_documents_nice_function_args(self):
        docs = Path("tech_connector/docs/API_FUNCTION_CATALOG.md").read_text(encoding="utf-8")

        self.assertIn("## DCC Index", docs)
        self.assertIn("- [maya](#maya)", docs)
        self.assertIn("- [unreal](#unreal)", docs)
        self.assertIn("### `api.dcc.maya.create_rig(...)`", docs)
        self.assertIn("`body_joint_map`, required", docs)
        self.assertIn("`face_joint_map`, required", docs)
        self.assertIn("### `api.dcc.maya.create_rig_mapping(...)`", docs)
        self.assertIn("`root_joint`, default `None`", docs)
        self.assertIn("### `api.dcc.unreal.find_asset_path_by_name(...)`", docs)
        self.assertIn("`file_name`, required", docs)
        self.assertIn("`expected_class`, default `''`", docs)
        self.assertIn("`directory`, default `'/Game'`", docs)
        self.assertIn("`allow_engine`, default `False`", docs)
        self.assertIn("prerequisite: [`api.dcc.maya.create_rig_mapping(...)`](#apidccmayacreate_rig_mapping)", docs)
        self.assertIn("-> `maya_tools.Rigging.mocap.setup_hik.create_rig_mapping`", docs)
        self.assertIn("Produces body_joint_map and face_joint_map", docs)
        self.assertIn("consumer: [`api.dcc.maya.create_rig(...)`](#apidccmayacreate_rig)", docs)
        self.assertIn("-> `maya_tools.Rigging.create_rig.create_rig_from_mapping`", docs)
        self.assertIn("Consumes this function's output in a known workflow.", docs)
        self.assertIn("### `api.dcc.maya.remove_head_module(...)`", docs)
        self.assertIn("[`api.dcc.maya.remove_arm_module(...)`](#apidccmayaremove_arm_module)", docs)
        self.assertIn("-> `maya_tools.Rigging.create_rig.remove_arm_module`", docs)
        self.assertIn("source [create_rig.py:", docs)

    def test_headless_api_docs_explain_public_arguments(self):
        docs = Path("tech_connector/docs/HEADLESS_API.md").read_text(encoding="utf-8")

        for term in (
            "settings",
            "project_root",
            "licensing_context",
            "commercial_use",
            "app_major_version",
            "require_entitlement",
            "entry_point",
            "extra_roots",
            "stamp_project_provenance",
            "host",
            "approved",
            "dry_run",
            "APIResult",
            "API_FUNCTION_CATALOG.md",
            "api.reasoning.run",
            "progress_callback",
            "canonical",
            "execute_tool",
            "api.features",
            "feature_id",
        ):
            self.assertIn(term, docs)


if __name__ == "__main__":
    unittest.main()
