import unittest
import json
import tempfile
from pathlib import Path

from tech_connector.services.capability_acquisition_service import AcquisitionEngine, AcquisitionStrategy
from tech_connector.services.ai_work_memory_service import _compact_entry
from tech_connector.services.chat_report_service import format_code_change_report
from tech_connector.services.github_ingest_service import _emit_progress
from tech_connector.services.version_control_service import GitProvider, _parse_git_status_porcelain, _parse_p4_opened, launch_github_cli_login
from tech_connector.services.integration_package_service import (
    bridge_setup_summary,
    create_integration_package,
    ensure_integration_bridge_manifests,
    load_integration_packages,
    summarize_integration_packages,
)
from tech_connector.services.diagnostic_service import _format_entry
from tech_connector.services.notification_service import (
    build_pipeline_message,
    fetch_discord_channels_and_users,
    fetch_slack_channels_and_users,
    send_discord_webhook,
    send_email_smtp,
    send_pipeline_output,
    send_slack_webhook,
)
from tech_connector.services.atlassian_service import (
    build_confluence_page_payload,
    build_jira_issue_payload,
    create_confluence_page,
    create_jira_issue,
    fetch_atlassian_projects_spaces_users,
)
from tech_connector.services.app_context_service import (
    active_app_context,
    app_context_for_token,
    app_context_prompt_block,
    slash_suggestions,
)
from tech_connector.services.editor_structure_service import python_structure_from_text
from tech_connector.services.connected_account_service import connected_application_status
from tech_connector.services.asset_mention_service import (
    candidates_from_app_context,
    merge_candidates,
    mention_context_block,
)
from tech_connector.ui.status_bar import format_status_card
from tech_connector.ui.pipeline_node_view import compact_tool_label, grouped_tool_symbols, public_tool_symbols


class DummyRegistry:
    def register_ingested_tool(self, *args, **kwargs):
        return []

    def save(self):
        return None


class TestGithubIngestAndAcquisition(unittest.TestCase):
    def test_emit_progress_supports_old_string_callbacks(self):
        events = []

        _emit_progress(events.append, "Downloading", 5, 10)

        self.assertEqual(events, ["Downloading"])

    def test_emit_progress_supports_detailed_callbacks(self):
        events = []

        _emit_progress(lambda msg, current, total: events.append((msg, current, total)), "Downloading", 5, 10)

        self.assertEqual(events, [("Downloading", 5, 10)])

    def test_github_search_strategy_requests_review_before_ingest(self):
        engine = AcquisitionEngine(DummyRegistry(), ".")
        strategy = AcquisitionStrategy(
            id="github_search_test",
            name="Search GitHub: test tool",
            source_type="github",
            source_url="https://github.com/search?q=test+tool&type=repositories",
            description="Search GitHub for a candidate tool.",
            capabilities_provided=["test tool"],
            estimated_minutes=10,
            success_probability=0.7,
            cost="Free",
            license="Varies",
            automation_level="Semi",
            compatibility={"*": "*"},
            risks=[],
            ranking_score=0.0,
            phase=1,
        )
        progress = []

        result = engine.execute_strategy(strategy, progress_cb=progress.append)

        self.assertTrue(result.success)
        self.assertIn("Web / GitHub Import", result.message)
        self.assertEqual(result.registered_capability_ids, [])
        self.assertTrue(any("requires selecting" in msg for msg in progress))

    def test_compact_memory_keeps_external_learning_paths(self):
        compact = _compact_entry(
            {
                "host": "workflow",
                "mode": "github_workflow_result",
                "label": "Approved external learning",
                "ok": True,
                "goal": "make a DCC workflow",
                "params": {
                    "source_url": "https://github.com/example/tool",
                    "local_path": "C:/tools/external/example_tool",
                    "workflow_path": "C:/project/workflows/maya/example.py",
                    "knowledge_path": "C:/project/knowledge/third_party/example.json",
                },
                "result": "Saved workflow from approved search result.",
            }
        )

        self.assertEqual(compact["source_url"], "https://github.com/example/tool")
        self.assertEqual(compact["local_path"], "C:/tools/external/example_tool")
        self.assertEqual(compact["workflow_path"], "C:/project/workflows/maya/example.py")
        self.assertEqual(compact["knowledge_path"], "C:/project/knowledge/third_party/example.json")

    def test_code_change_report_starts_with_compact_change_card(self):
        report = format_code_change_report(
            [
                {
                    "path": "C:/project/tool.py",
                    "action": "modify",
                    "before": "a\n",
                    "after": "a\nb\n",
                    "summary": "Added one line.",
                }
            ],
            include_diff=False,
        )

        self.assertIn("**Edited 1 file**", report)
        self.assertIn("[Undo last change](action://undo_last_applied)", report)
        self.assertIn("**Changed Files**", report)

    def test_git_mark_for_add_does_not_stage_implicitly(self):
        ok, msg = GitProvider().mark_for_add(__file__)

        self.assertTrue(ok)
        self.assertIn("untracked", msg.lower())

    def test_github_cli_login_missing_gh_points_to_install_and_token(self):
        from unittest import mock

        with mock.patch("tech_connector.services.version_control_service.subprocess.Popen", side_effect=FileNotFoundError()):
            ok, msg = launch_github_cli_login()

        self.assertFalse(ok)
        self.assertIn("https://cli.github.com/", msg)
        self.assertIn("https://github.com/settings/tokens", msg)

    def test_vcs_parsers_support_changelist_candidates(self):
        git_files = _parse_git_status_porcelain(" M app/tool.py\n?? new/file.py\nR  old.py -> new.py\n")
        p4_files = _parse_p4_opened("//depot/project/tool.py#3 - edit default change (text)\n")

        self.assertEqual(git_files[0]["path"], "app/tool.py")
        self.assertEqual(git_files[1]["status"], "??")
        self.assertEqual(git_files[2]["path"], "new.py")
        self.assertEqual(p4_files[0]["path"], "//depot/project/tool.py")
        self.assertEqual(p4_files[0]["status"], "edit")

    def test_git_current_changelists_reads_ai_studio_packages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            package = root / ".ai_studio" / "changelists" / "20260712_test"
            package.mkdir(parents=True)
            (package / "summary.json").write_text(
                json.dumps({"description": "Test package", "files": [{"path": "tool.py"}]}),
                encoding="utf-8",
            )

            ok, msg, items = GitProvider().current_changelists(root)

        self.assertTrue(ok)
        self.assertIn("1", msg)
        self.assertEqual(items[0]["description"], "Test package")
        self.assertEqual(items[0]["file_count"], 1)

    def test_create_integration_package_starts_untrusted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ok, msg, payload = create_integration_package(
                "Miro",
                "design_planning",
                "Add notes to design boards",
                "https://developers.miro.com/",
                base_dir=Path(temp_dir),
            )
            packages = load_integration_packages(Path(temp_dir))
            summary = summarize_integration_packages(Path(temp_dir))
            bridge_summary = bridge_setup_summary(Path(temp_dir))

        self.assertTrue(ok, msg)
        self.assertEqual(payload["type"], "design_planning")
        self.assertTrue(payload["connection"]["supports_bridge_setup"])
        self.assertIn("oauth_api", payload["connection"]["connector_types"])
        self.assertTrue(payload["bridge_manifest"]["supports_bridge_setup"])
        self.assertTrue(payload["lifecycle"]["discovered"])
        self.assertFalse(payload["lifecycle"]["connected"])
        self.assertFalse(payload["lifecycle"]["validated"])
        self.assertFalse(payload["lifecycle"]["trusted"])
        self.assertEqual(len(packages), 1)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["trusted"], 0)
        self.assertEqual(bridge_summary["supported"], 1)

    def test_bridge_manifest_backfill_updates_old_packages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "legacy_tool"
            (package / "bridge").mkdir(parents=True)
            (package / "package.json").write_text(
                json.dumps({
                    "schema": "ai_studio.integration_package.v1",
                    "id": "legacy_tool",
                    "name": "Legacy Tool",
                    "type": "communication",
                }),
                encoding="utf-8",
            )

            result = ensure_integration_bridge_manifests(root)
            packages = load_integration_packages(root)

        self.assertEqual(len(result["created"]), 1)
        self.assertTrue(packages[0]["bridge_manifest"]["supports_bridge_setup"])
        self.assertIn("webhook", packages[0]["bridge_manifest"]["connector_types"])

    def test_status_cards_are_compact_icon_first(self):
        text, style = format_status_card("unreal", "ok", "Connected to a very long project name")

        self.assertIn("unreal.png", text)
        self.assertIn("...", text)
        self.assertIn("font-size: 10px", style)

        vcs_text, _ = format_status_card("vcs", "ok", "Git connected")
        self.assertIn("git.png", vcs_text)
        gmail_text, _ = format_status_card("gmail", "ok", "Ready")
        self.assertIn("gmail.png", gmail_text)

    def test_pipeline_tool_menu_groups_symbols_by_app_and_action(self):
        grouped = grouped_tool_symbols(
            [
                {"name": "create_ik_control", "file_path": "C:/tools/maya/rigging.py", "kind": "function"},
                {"name": "add_mesh_cube", "file_path": "C:/tools/blender/modeling.py", "kind": "function"},
                {"name": "plain_helper", "file_path": "C:/project/tools.py", "kind": "function"},
            ]
        )

        self.assertIn("Maya", grouped)
        self.assertIn("Rigging", grouped["Maya"])
        self.assertEqual(grouped["Maya"]["Rigging"][0]["name"], "create_ik_control")
        self.assertIn("Blender", grouped)
        self.assertIn("Modeling", grouped["Blender"])
        self.assertIn("Project", grouped)
        self.assertIn("Project Tools", grouped["Project"])

    def test_pipeline_tool_menu_uses_provider_specific_taxonomies(self):
        grouped = grouped_tool_symbols(
            [
                {"name": "create_rig", "file_path": "C:/tools/maya/rigging.py", "kind": "function"},
                {"name": "get_changed_files", "provider_id": "github", "kind": "function", "public_tool": True},
                {"name": "create_page", "provider_id": "confluence", "kind": "function", "public_tool": True},
                {"name": "_version_key", "provider_id": "github", "kind": "function"},
            ]
        )

        self.assertIn("Maya", grouped)
        self.assertIn("Rigging", grouped["Maya"])
        self.assertNotIn("Pull Requests", grouped["Maya"])
        self.assertIn("GitHub", grouped)
        self.assertIn("Changes", grouped["GitHub"])
        self.assertNotIn("Rigging", grouped["GitHub"])
        self.assertIn("Confluence", grouped)
        self.assertIn("Pages", grouped["Confluence"])
        public_names = {symbol["name"] for symbol in public_tool_symbols([
            {"name": "_version_key", "provider_id": "github", "kind": "function"},
        ])}
        self.assertNotIn("_version_key", public_names)

    def test_pipeline_tool_search_label_includes_provider_and_category(self):
        label = compact_tool_label({
            "name": "get_changed_files",
            "provider_id": "github",
            "kind": "function",
            "public_tool": True,
        })

        self.assertEqual(label, "GitHub / Changes / get_changed_files")

    def test_backend_log_entries_render_commands_and_errors(self):
        rendered = _format_entry(
            {
                "time": "2026-07-12T12:00:00",
                "category": "test",
                "message": "Attempted command",
                "command": ["git", "status"],
                "cwd": "C:/repo",
                "returncode": 1,
                "stderr": "failed",
            }
        )

        self.assertIn("git status", rendered)
        self.assertIn("returncode: 1", rendered)
        self.assertIn("failed", rendered)

    def test_slack_webhook_posts_json_payload(self):
        calls = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"ok"

        def opener(request, timeout=20):
            calls.append((request, timeout, request.data))
            return Response()

        ok, msg = send_slack_webhook("https://hooks.slack.com/services/T/B/X", "hello", opener=opener)

        self.assertTrue(ok, msg)
        self.assertEqual(msg, "ok")
        self.assertIn(b'"text": "hello"', calls[0][2])

    def test_discord_webhook_posts_content_payload(self):
        calls = []

        class Response:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b""

        def opener(request, timeout=20):
            calls.append(request.data)
            return Response()

        ok, msg = send_discord_webhook("https://discord.com/api/webhooks/1/x", "hello", opener=opener)

        self.assertTrue(ok, msg)
        self.assertIn(b'"content": "hello"', calls[0])

    def test_email_smtp_uses_configured_server(self):
        events = []

        class FakeSmtp:
            def __init__(self, host, port):
                events.append(("connect", host, port))

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def starttls(self, context=None):
                events.append(("starttls", bool(context)))

            def login(self, username, password):
                events.append(("login", username, password))

            def send_message(self, msg):
                events.append(("send", msg["To"], msg["Subject"]))

        ok, msg = send_email_smtp(
            {
                "email_smtp_host": "smtp.gmail.com",
                "email_smtp_port": 587,
                "email_username": "user@example.com",
                "email_password": "token",
                "email_to": "dest@example.com",
                "email_use_tls": True,
            },
            "Subject",
            "Body",
            smtp_factory=FakeSmtp,
        )

        self.assertTrue(ok, msg)
        self.assertIn(("connect", "smtp.gmail.com", 587), events)
        self.assertIn(("login", "user@example.com", "token"), events)
        self.assertIn(("send", "dest@example.com", "Subject"), events)

    def test_pipeline_message_builder_includes_status_and_source(self):
        message = build_pipeline_message("Pipeline", "Body", status="ok", source="maya")

        self.assertIn("Pipeline", message)
        self.assertIn("Status: ok", message)
        self.assertIn("Source: maya", message)

    def test_atlassian_payload_builders(self):
        jira = build_jira_issue_payload("ABC", "Fix thing", "Details", issue_type="Bug", labels=["ai-studio"])
        page = build_confluence_page_payload("123", "Docs", "Line 1\nLine 2", parent_id="456")

        self.assertEqual(jira["fields"]["project"]["key"], "ABC")
        self.assertEqual(jira["fields"]["issuetype"]["name"], "Bug")
        self.assertEqual(jira["fields"]["labels"], ["ai-studio"])
        self.assertEqual(page["spaceId"], "123")
        self.assertEqual(page["parentId"], "456")
        self.assertIn("Line 1", page["body"]["value"])

    def test_atlassian_create_uses_expected_endpoints(self):
        calls = []

        class Response:
            status = 201

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body

        def opener(request, timeout=30):
            calls.append(request)
            if request.full_url.endswith("/rest/api/3/issue"):
                return Response(b'{"key":"ABC-1"}')
            return Response(b'{"id":"999"}')

        settings = {
            "atlassian_site_url": "https://example.atlassian.net",
            "atlassian_email": "me@example.com",
            "atlassian_api_token": "token",
        }
        jira_ok, jira_msg, _jira = create_jira_issue(settings, build_jira_issue_payload("ABC", "Task", "Body"), opener=opener)
        page_ok, page_msg, _page = create_confluence_page(settings, build_confluence_page_payload("123", "Docs", "Body"), opener=opener)

        self.assertTrue(jira_ok, jira_msg)
        self.assertTrue(page_ok, page_msg)
        self.assertTrue(calls[0].full_url.endswith("/rest/api/3/issue"))
        self.assertTrue(calls[1].full_url.endswith("/wiki/api/v2/pages"))

    def test_slash_app_context_parses_builtin_apps(self):
        context = active_app_context("/Maya @pCube")

        self.assertEqual(context.id, "maya")
        self.assertEqual(app_context_for_token("slack").id, "slack")
        self.assertTrue(any(item.id == "slack" for item in slash_suggestions("sla")))

    def test_app_context_scopes_mentions_for_slack_and_jira(self):
        slack = app_context_for_token("slack")
        slack_candidates = candidates_from_app_context(
            slack,
            {"slack_default_channel": "pipeline-alerts", "slack_channels": ["tools"], "slack_users": ["Casey"]},
        )
        slack_block = mention_context_block("/Slack send to @pipeline-alerts", slack_candidates)

        self.assertTrue(any(candidate.token == "pipeline-alerts" for candidate in slack_candidates))
        self.assertTrue(any(candidate.token == "tools" for candidate in slack_candidates))
        self.assertTrue(any(candidate.token == "Casey" for candidate in slack_candidates))
        self.assertIn("slack_channel", slack_block)

        jira = app_context_for_token("jira")
        jira_candidates = candidates_from_app_context(jira, {"jira_project_key": "TOOLS", "jira_projects": ["PIPE"], "atlassian_users": ["Dana"]})

        self.assertTrue(any(candidate.token == "TOOLS" for candidate in jira_candidates))
        self.assertTrue(any(candidate.token == "PIPE" for candidate in jira_candidates))
        self.assertTrue(any(candidate.token == "Dana" for candidate in jira_candidates))

    def test_slash_not_at_is_the_application_picker(self):
        candidates = merge_candidates(candidates_from_app_context(None), query="", limit=20)

        self.assertFalse(any(candidate.kind == "app_context" for candidate in candidates))
        self.assertTrue(any(item.id == "slack" for item in slash_suggestions("sla")))
        self.assertTrue(any(item.id == "maya" for item in slash_suggestions("may")))

    def test_app_context_prompt_block_describes_selected_application(self):
        block = app_context_prompt_block("/Confluence upload @page")

        self.assertIn("Selected Application Context", block)
        self.assertIn("Confluence", block)

    def test_editor_structure_extracts_classes_and_functions_only_with_sort_modes(self):
        source = (
            "VALUE = 1\n\n"
            "class Tool:\n"
            "    setting = 1\n\n"
            "    def zeta(self):\n"
            "        pass\n\n"
            "    def alpha(self, path: str) -> bool:\n"
            "        return True\n\n"
            "async def build():\n"
            "    return None\n"
        )
        items = python_structure_from_text(
            source,
            "tool.py",
        )

        names = [(item.name, item.kind, item.depth) for item in items]
        self.assertNotIn(("VALUE", "constant", 0), names)
        self.assertIn(("Tool", "class", 0), names)
        self.assertIn(("alpha", "function", 1), names)
        self.assertIn(("build", "async function", 0), names)
        self.assertTrue(next(item for item in items if item.name == "alpha").label().startswith("alpha("))
        self.assertFalse(next(item for item in items if item.name == "Tool").label().startswith("c_"))
        self.assertFalse(next(item for item in items if item.name == "alpha").label().startswith("f_"))
        self.assertLess([item.name for item in items].index("build"), [item.name for item in items].index("Tool"))
        self.assertLess([item.name for item in items].index("alpha"), [item.name for item in items].index("zeta"))

        natural = python_structure_from_text(source, "tool.py", sort_alpha=False)
        self.assertLess([item.name for item in natural].index("Tool"), [item.name for item in natural].index("build"))
        self.assertLess([item.name for item in natural].index("zeta"), [item.name for item in natural].index("alpha"))

    def test_connected_application_status_reports_real_capability_modes(self):
        rows = connected_application_status({"slack_webhook_url": "https://hooks.slack.test/1", "atlassian_api_token": ""})
        slack = next(row for row in rows if row["id"] == "slack")
        atlassian = next(row for row in rows if row["id"] == "atlassian")

        self.assertEqual(slack["mode"], "webhook only")
        self.assertIn("send output", slack["capabilities"])
        self.assertFalse(atlassian["connected"])

    def test_live_app_discovery_parses_channels_users_projects(self):
        class Response:
            status = 200

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.body

        def opener(request, timeout=30):
            url = request.full_url
            if "slack.com/api/conversations.list" in url:
                return Response(b'{"ok":true,"channels":[{"name":"pipeline-alerts"}]}')
            if "slack.com/api/users.list" in url:
                return Response(b'{"ok":true,"members":[{"name":"Casey","profile":{"display_name":"Casey"},"deleted":false,"is_bot":false}]}')
            if "/channels" in url:
                return Response(b'[{"name":"builds"}]')
            if "/members" in url:
                return Response(b'[{"nick":"Dana","user":{"username":"dana"}}]')
            if "/project/search" in url:
                return Response(b'{"values":[{"key":"TOOLS"}]}')
            if "/spaces" in url:
                return Response(b'{"results":[{"id":"SPACE"}]}')
            if "/user/search" in url:
                return Response(b'[{"displayName":"Morgan"}]')
            return Response(b"{}")

        slack_ok, slack_data, _ = fetch_slack_channels_and_users({"slack_bot_token": "xoxb"}, opener=opener)
        discord_ok, discord_data, _ = fetch_discord_channels_and_users({"discord_bot_token": "bot", "discord_guild_id": "123"}, opener=opener)
        atlassian_ok, atlassian_data, _ = fetch_atlassian_projects_spaces_users(
            {"atlassian_site_url": "https://example.atlassian.net", "atlassian_email": "a@example.com", "atlassian_api_token": "tok"},
            opener=opener,
        )

        self.assertTrue(slack_ok)
        self.assertIn("pipeline-alerts", slack_data["channels"])
        self.assertIn("Casey", slack_data["users"])
        self.assertTrue(discord_ok)
        self.assertIn("builds", discord_data["channels"])
        self.assertIn("Dana", discord_data["users"])
        self.assertTrue(atlassian_ok)
        self.assertIn("TOOLS", atlassian_data["projects"])
        self.assertIn("SPACE", atlassian_data["spaces"])
        self.assertIn("Morgan", atlassian_data["users"])


if __name__ == "__main__":
    unittest.main()
