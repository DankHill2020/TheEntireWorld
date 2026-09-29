"""Human-readable, privacy-minimal license acceptance receipt tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from tech_connector.licensing.acceptance import FileLicenseAcceptanceStore
from tech_connector.licensing.domain import EntitlementClaims
from tech_connector.tests.test_licensing_foundation import _payload


def test_acceptance_receipts_are_readable_and_do_not_store_sensitive_client_data(tmp_path):
    clock = lambda: datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    store = FileLicenseAcceptanceStore(tmp_path / "licensing", clock=clock)
    claims = EntitlementClaims.from_payload(_payload())

    store.record_local_notice(
        agreement_version="v2026.2",
        accepted_at="2026-09-28T11:55:00+00:00",
    )
    path = store.record_verified_entitlement(claims)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "tech_connector.license_acceptance_receipts.v1"
    assert [record["kind"] for record in payload["records"]] == [
        "local_license_notice",
        "verified_signed_agreement",
    ]
    signed = payload["records"][1]
    assert signed["license_id"] == "lic_test"
    assert signed["account_id"] == "acct_test"
    assert signed["agreement_version"] == "tc-community-test"
    assert signed["evidence"] == "ed25519_verified_entitlement"

    serialized = path.read_text(encoding="utf-8")
    assert "creator@example.com" not in serialized
    assert "C:/" not in serialized
    assert "signed_token" not in serialized
    assert "animation" not in serialized


def test_reverification_updates_one_signed_receipt_instead_of_duplicating_it(tmp_path):
    store = FileLicenseAcceptanceStore(tmp_path)
    first = EntitlementClaims.from_payload(_payload())
    refreshed_payload = _payload()
    refreshed_payload["jti"] = "ent_refreshed"
    refreshed = EntitlementClaims.from_payload(refreshed_payload)

    store.record_verified_entitlement(first)
    store.record_verified_entitlement(refreshed)

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert len(payload["records"]) == 1
    assert payload["records"][0]["last_verified_token_id"] == "ent_refreshed"
