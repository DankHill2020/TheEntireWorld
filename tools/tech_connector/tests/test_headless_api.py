import tempfile
import unittest
from pathlib import Path

from tech_connector.api import TechConnectorHeadlessAPI, call_function, execute_prompt_chain, plan_prompt_chain, verify_license
from tech_connector.services.license_entitlement_service import make_license_token


class HeadlessAPITests(unittest.TestCase):
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
            "license_secret",
            "require_entitlement",
            "entry_point",
            "extra_roots",
            "stamp_project_provenance",
            "host",
            "approved",
            "dry_run",
            "APIResult",
            "API_FUNCTION_CATALOG.md",
        ):
            self.assertIn(term, docs)


if __name__ == "__main__":
    unittest.main()
