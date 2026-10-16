import sqlite3
import tempfile
import unittest
from pathlib import Path

from tech_connector.services.dcc.dcc_smart_search_service import (
    active_hosts_from_context,
    smart_search_context_block,
    smart_search_suggestions,
)


class TestDccSmartSearchService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.maya_package = root / "maya_tools"
        self.unreal_package = root / "unreal_tools"
        self.maya_package.mkdir()
        self.unreal_package.mkdir()
        self.db_path = root / "index.sqlite"
        connection = sqlite3.connect(str(self.db_path))
        connection.executescript(
            """
            CREATE TABLE files (id INTEGER PRIMARY KEY, rel_path TEXT NOT NULL, module TEXT);
            CREATE TABLE symbols (
                id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL, name TEXT NOT NULL,
                qualname TEXT NOT NULL, kind TEXT NOT NULL, signature TEXT, docstring TEXT,
                source TEXT, start_line INTEGER
            );
            """
        )
        connection.execute(
            "INSERT INTO files VALUES (1, ?, ?)",
            ("maya_tools/Rigging/create_rig.py", "maya_tools.Rigging.create_rig"),
        )
        connection.execute(
            """
            INSERT INTO symbols(id, file_id, name, qualname, kind, signature, docstring)
            VALUES (1, 1, ?, ?, ?, ?, ?)
            """,
            (
                "create_rig_from_mapping", "create_rig_from_mapping", "function",
                "(body_joint_map, face_joint_map)", "Create a rig from mapped joints.",
            ),
        )
        connection.execute(
            "INSERT INTO files VALUES (3, ?, ?)",
            ("maya_tools/ui/spin_box.py", "maya_tools.ui.spin_box"),
        )
        connection.execute(
            """
            INSERT INTO symbols(id, file_id, name, qualname, kind, signature, docstring, source, start_line)
            VALUES (3, 3, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "FrameSpinBox",
                "FrameSpinBox",
                "class",
                "FrameSpinBox",
                "Frame selector widget.",
                "class FrameSpinBox(QSpinBox):\n    pass\n",
                12,
            ),
        )
        connection.execute(
            "INSERT INTO files VALUES (2, ?, ?)",
            ("unreal_tools/input.py", "unreal_tools.input"),
        )
        connection.execute(
            """
            INSERT INTO symbols(id, file_id, name, qualname, kind, signature, docstring)
            VALUES (2, 2, ?, ?, ?, ?, ?)
            """,
            ("create_action", "create_action", "function", "(asset_path)", "Create an input action."),
        )
        connection.execute(
            "INSERT INTO files VALUES (4, ?, ?)",
            ("unreal_tools/ui/spin_box.py", "unreal_tools.ui.spin_box"),
        )
        connection.execute(
            """
            INSERT INTO symbols(id, file_id, name, qualname, kind, signature, docstring, source, start_line)
            VALUES (4, 4, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "UnrealFrameSpinBox",
                "UnrealFrameSpinBox",
                "class",
                "UnrealFrameSpinBox",
                "Unreal frame selector widget.",
                "class UnrealFrameSpinBox(QtWidgets.QSpinBox):\n    pass\n",
                8,
            ),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    @property
    def package_dirs(self):
        return [self.maya_package, self.unreal_package]

    def test_root_prioritizes_active_application_and_continues(self):
        suggestions = smart_search_suggestions(
            "may", active_hosts=("maya",), package_dirs=self.package_dirs, db_path=self.db_path
        )

        self.assertEqual("Maya.", suggestions[0].token)
        self.assertTrue(suggestions[0].continues)
        self.assertEqual("active application", suggestions[0].kind)

    def test_application_dot_combines_operations_and_indexed_tools(self):
        suggestions = smart_search_suggestions(
            "Maya.create", package_dirs=self.package_dirs, db_path=self.db_path, limit=50
        )
        tokens = {item.token for item in suggestions}

        self.assertTrue(any(item.kind == "DCC operation" for item in suggestions))
        self.assertIn("maya_tools/Rigging.create_rig.create_rig_from_mapping", tokens)

    def test_package_slash_returns_only_package_functions(self):
        suggestions = smart_search_suggestions(
            "maya_tools/rig mapping", package_dirs=self.package_dirs, db_path=self.db_path
        )

        self.assertEqual(1, len(suggestions))
        self.assertEqual("tool function", suggestions[0].kind)
        self.assertEqual("maya_tools/Rigging.create_rig.create_rig_from_mapping", suggestions[0].token)
        self.assertFalse(any(item.kind == "DCC operation" for item in suggestions))

    def test_package_root_uses_slash_to_enter_function_only_mode(self):
        suggestions = smart_search_suggestions(
            "maya_t", package_dirs=self.package_dirs, db_path=self.db_path
        )

        package = next(item for item in suggestions if item.kind == "tool package")
        self.assertEqual("maya_tools/", package.token)
        self.assertTrue(package.continues)

    def test_context_block_resolves_registered_operation_and_function(self):
        text = "Use @Maya.scene.select then @maya_tools/Rigging.create_rig.create_rig_from_mapping"
        block = smart_search_context_block(text, db_path=self.db_path)

        self.assertIn("registered Maya operation `scene.select`", block)
        self.assertIn("indexed tool function", block)
        self.assertIn("maya_tools.Rigging.create_rig.create_rig_from_mapping", block)

    def test_active_hosts_uses_cached_router_context(self):
        context = "Active DCC Context:\n- Active DCC Host: Maya\n- Active DCC Host: Unreal Engine (Bridge Active)"

        self.assertEqual(("maya", "unreal"), active_hosts_from_context(context))

    def test_desktop_dot_exposes_window_inspection_operation(self):
        suggestions = smart_search_suggestions(
            "Desktop.window", package_dirs=self.package_dirs, db_path=self.db_path
        )

        self.assertEqual("Desktop.window.inspect", suggestions[0].token)
        self.assertFalse(suggestions[0].continues)
        self.assertFalse(getattr(suggestions[0], "mutates_project", False))

    def test_package_bang_filters_classes_by_base_type(self):
        suggestions = smart_search_suggestions(
            "maya_tools!QSpinBox", package_dirs=self.package_dirs, db_path=self.db_path
        )

        self.assertEqual(1, len(suggestions))
        self.assertEqual("tool class", suggestions[0].kind)
        self.assertEqual("maya_tools!ui.spin_box.FrameSpinBox", suggestions[0].token)
        self.assertIn("inherits QSpinBox", suggestions[0].detail)

    def test_global_bang_filters_classes_across_packages(self):
        suggestions = smart_search_suggestions(
            "!QSpinBox", package_dirs=self.package_dirs, db_path=self.db_path
        )
        tokens = {item.token for item in suggestions}

        self.assertIn("!maya_tools.ui.spin_box.FrameSpinBox", tokens)
        self.assertIn("!unreal_tools.ui.spin_box.UnrealFrameSpinBox", tokens)

    def test_context_block_resolves_class_type_reference(self):
        block = smart_search_context_block(
            "Use @maya_tools!ui.spin_box.FrameSpinBox", db_path=self.db_path
        )

        self.assertIn("indexed tool class", block)
        self.assertIn("maya_tools.ui.spin_box.FrameSpinBox", block)

    def test_connected_service_root_reports_readiness_and_continues(self):
        suggestions = smart_search_suggestions(
            "sla",
            package_dirs=self.package_dirs,
            db_path=self.db_path,
            settings={"slack_webhook_url": "https://hooks.slack.invalid/test"},
        )

        slack = next(item for item in suggestions if item.token == "Slack.")
        self.assertTrue(slack.continues)
        self.assertEqual("connected application", slack.kind)
        self.assertIn("connected", slack.detail)

    def test_connected_service_dot_lists_configured_targets(self):
        suggestions = smart_search_suggestions(
            "sLaCk.pipe",
            package_dirs=self.package_dirs,
            db_path=self.db_path,
            settings={
                "slack_bot_token": "xoxb-test",
                "slack_channels": ["pipeline-alerts", "general"],
            },
        )

        self.assertEqual(["Slack.pipeline-alerts"], [item.token for item in suggestions])
        self.assertIn("connected", suggestions[0].detail)

    def test_connected_service_context_never_hides_missing_setup(self):
        block = smart_search_context_block(
            "Send this to @Slack.here",
            db_path=self.db_path,
            settings={},
        )

        self.assertIn("Slack target `here`", block)
        self.assertIn("connection=setup required", block)
        self.assertIn("Do not silently substitute another target", block)

    def test_unknown_connected_service_target_is_explicitly_unresolved(self):
        block = smart_search_context_block(
            "Send this to @Slack.does-not-exist",
            db_path=self.db_path,
            settings={"slack_webhook_url": "https://hooks.slack.invalid/test"},
        )

        self.assertIn("unresolved Slack target", block)
        self.assertIn("Resolve or ask for clarification before acting", block)

    def test_jira_completion_requires_project_before_issue_type(self):
        settings = {
            "atlassian_site_url": "https://example.atlassian.net",
            "atlassian_email": "artist@example.com",
            "atlassian_api_token": "secret",
            "jira_project_key": "ART",
        }

        projects = smart_search_suggestions(
            "Jira.", package_dirs=self.package_dirs, db_path=self.db_path, settings=settings
        )
        issue_types = smart_search_suggestions(
            "Jira.ART.b", package_dirs=self.package_dirs, db_path=self.db_path, settings=settings
        )

        self.assertEqual(["Jira.ART."], [item.token for item in projects])
        self.assertTrue(projects[0].continues)
        self.assertEqual(["Jira.ART.bug"], [item.token for item in issue_types])

    def test_confluence_completion_uses_configured_space_not_page_placeholder(self):
        settings = {
            "atlassian_site_url": "https://example.atlassian.net",
            "atlassian_email": "artist@example.com",
            "atlassian_api_token": "secret",
            "confluence_space_id": "ARTDOCS",
        }

        suggestions = smart_search_suggestions(
            "Confluence.", package_dirs=self.package_dirs, db_path=self.db_path, settings=settings
        )

        self.assertEqual(["Confluence.ARTDOCS"], [item.token for item in suggestions])


if __name__ == "__main__":
    unittest.main()
