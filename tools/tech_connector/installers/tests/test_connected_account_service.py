import os
import unittest

from tech_connector.services.connected_account_service import (
    clear_connected_account,
    connected_account_status,
    connected_account_status_rows,
    connected_application_status,
    connected_account_summary,
    mask_secret,
    update_connected_account,
)


class ConnectedAccountServiceTests(unittest.TestCase):
    def test_mask_secret_keeps_short_values_hidden(self):
        self.assertEqual(mask_secret("abc"), "***")
        self.assertEqual(mask_secret("abcdefghijkl"), "abcd...ijkl")
        self.assertEqual(mask_secret(""), "")

    def test_github_reports_token_connection_and_masks_secret(self):
        row = connected_account_status({"github_username": "artist", "github_token": "ghp_1234567890"}, "github")
        self.assertTrue(row["connected"])
        self.assertIn("artist", row["mode"])
        token_field = next(field for field in row["fields"] if field["key"] == "github_token")
        self.assertEqual(token_field["value"], "ghp_...7890")

    def test_github_can_resolve_token_from_environment(self):
        old = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "envtoken123"
        try:
            row = connected_account_status({}, "github")
            self.assertTrue(row["connected"])
            token_field = next(field for field in row["fields"] if field["key"] == "github_token")
            self.assertEqual(token_field["source"], "environment")
        finally:
            if old is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old

    def test_messaging_modes_distinguish_webhook_and_bot_access(self):
        slack = connected_account_status({"slack_webhook_url": "https://hooks.slack.test/1"}, "slack")
        self.assertTrue(slack["connected"])
        self.assertEqual(slack["mode"], "webhook only")
        self.assertEqual(slack["capabilities"], ["send output"])

        discord = connected_account_status({"discord_bot_token": "bot-token"}, "discord")
        self.assertTrue(discord["connected"])
        self.assertIn("guild ID missing", discord["mode"])

    def test_perforce_requires_core_workspace_fields(self):
        partial = connected_account_status({"p4_port": "ssl:p4:1666", "p4_user": "artist"}, "perforce")
        self.assertFalse(partial["connected"])
        self.assertEqual(partial["missing_fields"], ["P4CLIENT"])

        complete = connected_account_status(
            {"p4_port": "ssl:p4:1666", "p4_user": "artist", "p4_client": "tools_ws"},
            "perforce",
        )
        self.assertTrue(complete["connected"])
        self.assertIn("tools_ws", complete["mode"])

    def test_update_and_clear_write_legacy_settings_keys(self):
        settings = {}
        updated = update_connected_account(
            settings,
            "slack",
            {"slack_bot_token": "xoxb-token", "slack_default_channel": "tools", "ignored": "nope"},
        )
        self.assertTrue(updated["connected"])
        self.assertEqual(settings["slack_bot_token"], "xoxb-token")
        self.assertNotIn("ignored", settings)

        cleared = clear_connected_account(settings, "slack")
        self.assertFalse(cleared["connected"])
        self.assertEqual(settings["slack_bot_token"], "")
        self.assertEqual(settings["slack_default_channel"], "")

    def test_summary_and_connected_app_rows_include_vcs_and_messaging(self):
        settings = {
            "github_token": "tok",
            "slack_webhook_url": "https://hooks.slack.test/1",
            "atlassian_site_url": "https://example.atlassian.net",
            "atlassian_email": "a@example.com",
            "atlassian_api_token": "api",
        }
        summary = connected_account_summary(settings)
        self.assertIn("github", summary["connected"])
        self.assertIn("slack", summary["connected"])
        self.assertIn("atlassian", summary["connected"])

        rows = connected_account_status_rows(settings)
        self.assertTrue(any(row["id"] == "perforce" for row in rows))

        app_rows = connected_application_status(settings)
        by_id = {row["id"]: row for row in app_rows}
        self.assertTrue(by_id["github"]["connected"])
        self.assertEqual(by_id["slack"]["mode"], "webhook only")
        self.assertEqual(by_id["atlassian"]["category"], "Ops/Documentation")


if __name__ == "__main__":
    unittest.main()
