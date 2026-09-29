import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from unittest.mock import patch

from tech_connector.services.license_entitlement_service import (
    clear_license_login,
    entitlement_status_row,
    make_license_token,
    requires_community_residual,
    update_license_login,
    verify_entitlement,
    verify_license_token,
)


class LicenseEntitlementServiceTests(unittest.TestCase):
    def setUp(self):
        self.legacy_environment = patch.dict(
            "os.environ",
            {"TECH_CONNECTOR_ALLOW_LEGACY_ENTITLEMENT": "1"},
        )
        self.legacy_environment.start()

    def tearDown(self):
        self.legacy_environment.stop()

    def setUp(self):
        self.legacy_environment = patch.dict(
            "os.environ",
            {"TECH_CONNECTOR_ALLOW_LEGACY_ENTITLEMENT": "1"},
        )
        self.legacy_environment.start()

    def tearDown(self):
        self.legacy_environment.stop()

    def test_login_required_locks_without_token(self):
        entitlement = verify_entitlement({"tech_connector_require_login": True})

        self.assertFalse(entitlement.unlocked)
        self.assertEqual("locked", entitlement.tier)
        self.assertIn("required", entitlement.reason.lower())

    def test_personal_token_unlocks_same_app_without_resale(self):
        secret = "dev-secret"
        token = make_license_token(
            {
                "sub": "acct_123",
                "email": "creator@example.com",
                "tier": "personal",
                "license_id": "lic_personal",
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            },
            secret,
        )

        entitlement = verify_entitlement({"tech_connector_license_token": token}, secret=secret)

        self.assertTrue(entitlement.unlocked)
        self.assertEqual("personal", entitlement.tier)
        self.assertIn("small_studio_commercial_grace", entitlement.capabilities)
        self.assertIn("official_api_access", entitlement.capabilities)
        self.assertFalse(entitlement.resale_allowed)
        self.assertFalse(entitlement.hosted_access_allowed)
        self.assertFalse(entitlement.ai_training_allowed)
        self.assertFalse(entitlement.direct_code_reuse_allowed)
        self.assertTrue(entitlement.official_api_required)

    def test_enterprise_token_unlocks_enterprise_capabilities_but_not_resale(self):
        secret = "dev-secret"
        token = make_license_token(
            {
                "sub": "acct_ent",
                "email": "lead@example.com",
                "organization": "Big Studio",
                "tier": "enterprise",
                "license_id": "lic_enterprise",
                "features": ["priority_support"],
            },
            secret,
        )

        row = entitlement_status_row({"tech_connector_license_token": token}, secret=secret)

        self.assertTrue(row["connected"])
        self.assertEqual("enterprise", row["tier"])
        self.assertIn("enterprise_pipeline", row["capabilities"])
        self.assertIn("full_automation", row["capabilities"])
        self.assertIn("official_api_access", row["capabilities"])
        self.assertIn("priority_support", row["capabilities"])
        self.assertFalse(row["resale_allowed"])
        self.assertFalse(row["ai_training_allowed"])
        self.assertFalse(row["direct_code_reuse_allowed"])
        self.assertTrue(row["official_api_required"])

    def test_expired_or_tampered_token_fails(self):
        secret = "dev-secret"
        expired = make_license_token(
            {
                "email": "creator@example.com",
                "tier": "personal",
                "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            },
            secret,
        )
        ok, _payload, reason = verify_license_token(expired, secret=secret)
        self.assertFalse(ok)
        self.assertIn("expired", reason.lower())

        tampered = expired[:-2] + "xx"
        ok, _payload, reason = verify_license_token(tampered, secret=secret)
        self.assertFalse(ok)
        self.assertIn("signature", reason.lower())

    def test_community_residual_starts_only_above_project_profit_threshold(self):
        secret = "dev-secret"
        token = make_license_token({"email": "creator@example.com", "tier": "personal"}, secret)
        settings = {"tech_connector_license_token": token}

        self.assertFalse(requires_community_residual(settings, adjusted_project_profit_usd=100_000, secret=secret))
        self.assertFalse(requires_community_residual(settings, adjusted_project_profit_usd=500_000, secret=secret))
        self.assertTrue(requires_community_residual(settings, adjusted_project_profit_usd=500_001, secret=secret))

    def test_commercial_tier_covers_commercial_threshold(self):
        secret = "dev-secret"
        token = make_license_token({"email": "biz@example.com", "tier": "commercial"}, secret)
        settings = {"tech_connector_license_token": token}

        self.assertFalse(requires_community_residual(settings, adjusted_project_profit_usd=900_000, secret=secret))

    def test_update_and_clear_license_login(self):
        secret = "dev-secret"
        token = make_license_token({"email": "creator@example.com", "tier": "personal"}, secret)
        settings = {}

        row = update_license_login(settings, email="creator@example.com", token=token)

        self.assertTrue(settings["tech_connector_account_email"])
        self.assertTrue(settings["tech_connector_license_token"])
        self.assertFalse(row["connected"])

        row = entitlement_status_row(settings, secret=secret)
        self.assertTrue(row["connected"])

        row = clear_license_login(settings)
        self.assertFalse(row["connected"])
        self.assertEqual("", settings["tech_connector_license_token"])


if __name__ == "__main__":
    unittest.main()
