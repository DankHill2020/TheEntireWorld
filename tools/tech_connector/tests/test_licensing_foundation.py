from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tech_connector.api import TechConnectorHeadlessAPI
from tech_connector.licensing.configuration import LicensingConfiguration
from tech_connector.licensing.context import LicensingContext
from tech_connector.licensing.domain import LicenseMarketSegment, LicenseType, PolicyContext
from tech_connector.licensing.economics import estimate_residual_minor
from tech_connector.licensing.local_storage import (
    FileEntitlementStore,
    FileLicensingAuditSink,
    InstallationDeviceIdentity,
)
from tech_connector.licensing.policy import evaluate_entitlement
from tech_connector.licensing.project_identity import ensure_project_identity
from tech_connector.licensing.verification import EntitlementTokenVerifier, TokenVerificationError
from tech_connector.packaging.stage_package import validate_staged_package


NOW = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    return _b64(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def _sign(payload: dict, private_key: Ed25519PrivateKey, key_id: str = "test-key") -> str:
    header = {"typ": "TC-ENT", "alg": "EdDSA", "kid": key_id}
    encoded_header = _b64(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    encoded_payload = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    return f"{encoded_header}.{encoded_payload}.{_b64(private_key.sign(signing_input))}"


@pytest.fixture()
def signing_material():
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    verifier = EntitlementTokenVerifier.from_base64_keys(
        {"test-key": _b64(public_bytes)},
        issuer="https://license.theentireworld.com",
        audience="tech-connector",
        clock_skew_seconds=0,
    )
    return private_key, verifier


def _payload(license_type: str = "community") -> dict:
    return {
        "schema_version": 1,
        "iss": "https://license.theentireworld.com",
        "aud": ["tech-connector"],
        "sub": "acct_test",
        "jti": "ent_test",
        "iat": int(NOW.timestamp()),
        "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
        "exp": int((NOW + timedelta(days=120)).timestamp()),
        "principal": {
            "account_id": "acct_test",
            "email": "creator@example.com",
            "email_verified": True,
            "organization_id": "org_test",
            "organization_name": "Test Studio",
            "organization_role": "license_admin",
            "studio_size_band": "micro",
        },
        "license": {
            "license_id": "lic_test",
            "type": license_type,
            "status": "active",
            "grantee_type": "organization",
            "grantee_id": "org_test",
            "agreement_version": "tc-community-test",
            "accepted_at": NOW.isoformat(),
        },
        "projects": {
            "registration_required": license_type == "community",
            "authorization_mode": "explicit" if license_type == "community" else "any",
            "authorized": [
                {
                    "project_id": "prj_authorized",
                    "status": "active",
                    "commercial_use": True,
                    "terms_id": "terms_test",
                }
            ],
        },
        "terms": {
            "terms_id": "terms_test",
            "version": 1,
            "effective_at": NOW.isoformat(),
            "calculation_basis": "adjusted_project_profit",
            "currency": "USD",
            "profit_threshold_minor": 50_000_000,
            "threshold_period": "project_lifetime",
            "receipts_basis": "all_project_receipts",
            "eligible_cost_standard": "actual_documented_direct_reasonable_necessary",
            "owner_labor_standard": "actual_compensation_or_preagreed_capped_allowance",
            "related_party_standard": "lower_of_actual_cost_or_arm_length_fair_market_value",
            "shared_cost_allocation_standard": "documented_consistent_proportionate_allocation",
            "excluded_cost_categories": [
                "owner_distributions",
                "unrelated_overhead",
                "inflated_related_party_charges",
                "double_counted_costs",
            ],
            "rate_basis_points": 75,
            "reporting_period": "quarterly",
        },
        "version_entitlement": {
            "product": "tech_connector",
            "perpetual_major_versions": ["7"],
            "updates_through": (NOW + timedelta(days=365)).isoformat(),
        },
        "support": {
            "level": "standard",
            "expires_at": (NOW + timedelta(days=365)).isoformat(),
        },
        "limits": {"seat_count": 1, "device_limit_per_seat": 2},
        "activation": {
            "activation_id": "act_test",
            "device_id_hash": "device_hash",
            "active_device_count": 1,
        },
        "offline": {
            "refresh_after": (NOW + timedelta(days=30)).isoformat(),
            "expires_at": (NOW + timedelta(days=90)).isoformat(),
        },
        "capabilities": ["commercial_use", "dcc_host_access", "official_api_access"],
    }


def _payload_v2(
    market_segment: str,
    *,
    license_type: str = "community",
    offer_id: str = "offer-test-2026",
) -> dict:
    payload = _payload(license_type)
    payload["schema_version"] = 2
    payload["license"].update(
        {
            "market_segment": market_segment,
            "offer_id": offer_id,
            "classification_version": "studio-size-2026.1",
        }
    )
    if market_segment == "enterprise":
        payload["capabilities"].append("enterprise_use")
    if market_segment in {"indie", "enterprise"}:
        payload["seat_assignment"] = {
            "assignment_id": "seat_test",
            "account_id": "acct_test",
            "status": "active",
            "assigned_at": NOW.isoformat(),
        }
    return payload


def _context(**overrides) -> PolicyContext:
    values = {
        "now": NOW,
        "product": "tech_connector",
        "app_major_version": "7",
        "project_id": "prj_authorized",
        "commercial_use": True,
        "device_id_hash": "device_hash",
    }
    values.update(overrides)
    return PolicyContext(**values)


def _runtime_context(root, private_key: Ed25519PrivateKey) -> LicensingContext:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    configuration = LicensingConfiguration(
        product="tech_connector",
        issuer="https://license.theentireworld.com",
        audience="tech-connector",
        clock_skew_seconds=0,
        maximum_offline_days=90,
        endpoints={},
        public_keys={"test-key": _b64(public_bytes)},
    )
    return LicensingContext(
        configuration,
        entitlement_store=FileEntitlementStore(root / "licensing"),
        device_identity=InstallationDeviceIdentity(root / "licensing"),
    )


@pytest.mark.parametrize("license_type", [item.value for item in LicenseType])
def test_all_license_types_round_trip(signing_material, license_type):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload(license_type), private_key), now=NOW)
    assert claims.license.type.value == license_type
    assert evaluate_entitlement(claims, _context()).allowed


@pytest.mark.parametrize(
    ("market_segment", "license_type"),
    (
        ("community", "community"),
        ("indie", "community"),
        ("indie", "perpetual"),
        ("enterprise", "custom"),
    ),
)
def test_v2_market_segments_round_trip(
    signing_material,
    market_segment,
    license_type,
):
    private_key, verifier = signing_material
    claims = verifier.verify(
        _sign(_payload_v2(market_segment, license_type=license_type), private_key),
        now=NOW,
    )

    assert claims.schema_version == 2
    assert claims.license.market_segment.value == market_segment
    assert claims.license.offer_id == "offer-test-2026"
    assert evaluate_entitlement(claims, _context()).allowed


@pytest.mark.parametrize(
    ("license_type", "expected_segment"),
    (
        ("community", LicenseMarketSegment.COMMUNITY),
        ("perpetual", LicenseMarketSegment.CUSTOM),
        ("custom", LicenseMarketSegment.CUSTOM),
    ),
)
def test_v1_entitlements_remain_compatible(
    signing_material,
    license_type,
    expected_segment,
):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload(license_type), private_key), now=NOW)

    assert claims.schema_version == 1
    assert claims.license.market_segment is expected_segment
    assert claims.license.offer_id == "legacy-v1"


def test_indie_economics_come_from_signed_terms_not_client_tier_constants(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("indie", license_type="community", offer_id="indie-success-a")
    payload["terms"]["rate_basis_points"] = 35
    payload["terms"]["profit_threshold_minor"] = 50_000_000

    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    assert claims.license.market_segment is LicenseMarketSegment.INDIE
    assert claims.terms.rate_basis_points == 35
    assert claims.terms.profit_threshold_minor == 50_000_000
    assert evaluate_entitlement(claims, _context()).allowed
    assert estimate_residual_minor(claims.terms, 100_000_000) == 175_000


def test_signed_marginal_residual_schedule_round_trips(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("indie", license_type="community", offer_id="community-micro-2026a")
    payload["terms"].update(
        {
            "calculation_method": "marginal_brackets",
            "rate_basis_points": 0,
            "residual_brackets": [
                {
                    "from_profit_minor": 50_000_000,
                    "to_profit_minor": 100_000_000,
                    "rate_basis_points": 75,
                },
                {
                    "from_profit_minor": 100_000_000,
                    "to_profit_minor": 500_000_000,
                    "rate_basis_points": 100,
                },
                {
                    "from_profit_minor": 500_000_000,
                    "to_profit_minor": None,
                    "rate_basis_points": 125,
                },
            ],
        }
    )

    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    assert claims.terms.calculation_method == "marginal_brackets"
    assert [item.rate_basis_points for item in claims.terms.residual_brackets] == [
        75,
        100,
        125,
    ]
    assert claims.terms.residual_brackets[-1].to_profit_minor is None
    assert evaluate_entitlement(claims, _context()).allowed
    assert estimate_residual_minor(claims.terms, 50_000_000) == 0
    # $500k at 0.75% plus $1m at 1.00% = $13,750.
    assert estimate_residual_minor(claims.terms, 200_000_000) == 1_375_000


@pytest.mark.parametrize(
    ("brackets", "message"),
    (
        (
            [
                {
                    "from_profit_minor": 60_000_000,
                    "to_profit_minor": None,
                    "rate_basis_points": 75,
                }
            ],
            "contiguous from the profit threshold",
        ),
        (
            [
                {
                    "from_profit_minor": 50_000_000,
                    "to_profit_minor": 100_000_000,
                    "rate_basis_points": 100,
                },
                {
                    "from_profit_minor": 100_000_000,
                    "to_profit_minor": None,
                    "rate_basis_points": 75,
                },
            ],
            "rates must not decrease",
        ),
        (
            [
                {
                    "from_profit_minor": 50_000_000,
                    "to_profit_minor": 100_000_000,
                    "rate_basis_points": 75,
                }
            ],
            "final residual bracket must be open-ended",
        ),
    ),
)
def test_invalid_marginal_residual_schedules_are_rejected(
    signing_material,
    brackets,
    message,
):
    private_key, verifier = signing_material
    payload = _payload_v2("indie", license_type="community")
    payload["terms"].update(
        {
            "calculation_method": "marginal_brackets",
            "rate_basis_points": 0,
            "residual_brackets": brackets,
        }
    )

    with pytest.raises(TokenVerificationError, match=message):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_enterprise_requires_signed_capability(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("enterprise", license_type="custom")
    payload["capabilities"].remove("enterprise_use")
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    decision = evaluate_entitlement(claims, _context())

    assert not decision.allowed
    assert decision.code == "enterprise_capability_missing"


def test_enterprise_requires_organization_grantee(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("enterprise", license_type="custom")
    payload["principal"]["organization_id"] = ""
    payload["license"]["grantee_type"] = "individual"
    payload["license"]["grantee_id"] = "acct_test"

    with pytest.raises(TokenVerificationError, match="organization grantee"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_indie_and_enterprise_require_named_user_seat_assignment(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("indie", license_type="perpetual")
    payload.pop("seat_assignment")

    with pytest.raises(TokenVerificationError, match="named-user seat_assignment"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_named_user_seat_must_match_authenticated_account(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("enterprise", license_type="custom")
    payload["seat_assignment"]["account_id"] = "acct_someone_else"

    with pytest.raises(TokenVerificationError, match="must match principal.account_id"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_named_user_device_limit_is_per_seat_not_organization_pool(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("enterprise", license_type="custom")
    payload["limits"] = {"seat_count": 20, "device_limit_per_seat": 2}
    payload["activation"]["active_device_count"] = 3
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    decision = evaluate_entitlement(claims, _context())

    assert not decision.allowed
    assert decision.code == "device_limit_exceeded"


def test_inactive_named_user_seat_is_denied(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("indie", license_type="perpetual")
    payload["seat_assignment"]["status"] = "revoked"
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    decision = evaluate_entitlement(claims, _context())

    assert not decision.allowed
    assert decision.code == "seat_assignment_inactive"


def test_v2_rejects_inconsistent_community_market_segment(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("community", license_type="perpetual")

    with pytest.raises(TokenVerificationError, match="community license type"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_v2_indie_requires_auditable_studio_size_classification(signing_material):
    private_key, verifier = signing_material
    payload = _payload_v2("indie", license_type="community")
    payload["principal"]["studio_size_band"] = ""

    with pytest.raises(TokenVerificationError, match="studio_size_band"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_unregistered_community_project_is_allowed_for_noncommercial_use(signing_material):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload(), private_key), now=NOW)

    decision = evaluate_entitlement(
        claims,
        _context(project_id="prj_hobby", commercial_use=False),
    )

    assert decision.allowed
    assert decision.project is None


def test_unregistered_community_project_still_fails_for_commercial_use(signing_material):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload(), private_key), now=NOW)

    decision = evaluate_entitlement(
        claims,
        _context(project_id="prj_commercial", commercial_use=True),
    )

    assert not decision.allowed
    assert decision.code == "project_registration_required"


def test_tampering_invalidates_entitlement(signing_material):
    private_key, verifier = signing_material
    token = _sign(_payload(), private_key)
    header, payload, signature = token.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    with pytest.raises(TokenVerificationError, match="signature"):
        verifier.verify(f"{header}.{payload[:-1]}{replacement}.{signature}", now=NOW)


def test_token_expiration_is_enforced(signing_material):
    private_key, verifier = signing_material
    payload = _payload()
    payload["exp"] = int((NOW - timedelta(seconds=1)).timestamp())
    with pytest.raises(TokenVerificationError, match="expired"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_public_key_overlap_accepts_old_and_new_then_removal_rejects_old() -> None:
    old_private_key = Ed25519PrivateKey.generate()
    new_private_key = Ed25519PrivateKey.generate()
    overlap = EntitlementTokenVerifier.from_base64_keys(
        {
            "2026-old": _public_key_b64(old_private_key),
            "2026-new": _public_key_b64(new_private_key),
        },
        issuer="https://license.theentireworld.com",
        audience="tech-connector",
        clock_skew_seconds=0,
    )
    old_token = _sign(_payload(), old_private_key, key_id="2026-old")
    new_token = _sign(_payload(), new_private_key, key_id="2026-new")

    assert overlap.verify(old_token, now=NOW).token_id == "ent_test"
    assert overlap.verify(new_token, now=NOW).token_id == "ent_test"

    after_rotation = EntitlementTokenVerifier.from_base64_keys(
        {"2026-new": _public_key_b64(new_private_key)},
        issuer="https://license.theentireworld.com",
        audience="tech-connector",
        clock_skew_seconds=0,
    )
    assert after_rotation.verify(new_token, now=NOW).token_id == "ent_test"
    with pytest.raises(TokenVerificationError, match="unknown signing key"):
        after_rotation.verify(old_token, now=NOW)


@pytest.mark.parametrize("offline_days", [30, 60, 90])
def test_configured_offline_windows_expire_at_the_exact_boundary(
    signing_material,
    offline_days,
) -> None:
    private_key, verifier = signing_material
    payload = _payload()
    offline_expiration = NOW + timedelta(days=offline_days)
    payload["offline"] = {
        "refresh_after": (NOW + timedelta(days=max(1, offline_days // 2))).isoformat(),
        "expires_at": offline_expiration.isoformat(),
    }
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    before_boundary = evaluate_entitlement(
        claims,
        _context(now=offline_expiration - timedelta(seconds=1)),
    )
    at_boundary = evaluate_entitlement(claims, _context(now=offline_expiration))

    assert before_boundary.allowed
    assert not at_boundary.allowed
    assert at_boundary.code == "offline_expired"


def test_offline_window_above_configured_maximum_is_rejected(signing_material) -> None:
    private_key, verifier = signing_material
    payload = _payload()
    payload["offline"]["expires_at"] = (NOW + timedelta(days=91)).isoformat()

    with pytest.raises(TokenVerificationError, match="configured maximum"):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_offline_refresh_warning_and_hard_expiration(signing_material):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload(), private_key), now=NOW)

    warning = evaluate_entitlement(claims, _context(now=NOW + timedelta(days=31)))
    expired = evaluate_entitlement(claims, _context(now=NOW + timedelta(days=91)))

    assert warning.allowed and warning.warnings
    assert not expired.allowed
    assert expired.code == "offline_expired"


def test_device_activation_limit_and_device_binding(signing_material):
    private_key, verifier = signing_material
    payload = _payload()
    payload["activation"]["active_device_count"] = 3
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    assert evaluate_entitlement(claims, _context()).code == "device_limit_exceeded"

    payload["activation"]["active_device_count"] = 1
    claims = verifier.verify(_sign(payload, private_key), now=NOW)
    assert evaluate_entitlement(claims, _context(device_id_hash="replacement_device")).code == "device_mismatch"


def test_organization_device_limit_uses_all_entitled_seats(signing_material):
    private_key, verifier = signing_material
    payload = _payload()
    payload["limits"] = {"seat_count": 2, "device_limit_per_seat": 2}
    payload["activation"]["active_device_count"] = 3
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    assert evaluate_entitlement(claims, _context()).allowed


def test_community_commercial_use_requires_registered_authorized_project(signing_material):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload("community"), private_key), now=NOW)

    denied = evaluate_entitlement(claims, _context(project_id="prj_unregistered"))
    allowed = evaluate_entitlement(claims, _context(project_id="prj_authorized"))

    assert denied.code == "project_registration_required"
    assert allowed.allowed
    assert claims.terms is not None
    assert claims.terms.calculation_basis == "adjusted_project_profit"
    assert claims.terms.profit_threshold_minor == 50_000_000
    assert claims.terms.threshold_period == "project_lifetime"
    assert claims.terms.owner_labor_standard == "actual_compensation_or_preagreed_capped_allowance"
    assert claims.terms.related_party_standard == "lower_of_actual_cost_or_arm_length_fair_market_value"


def test_community_rejects_non_lifetime_threshold_terms(signing_material):
    private_key, verifier = signing_material
    payload = _payload("community")
    payload["terms"]["threshold_period"] = "rolling_12_months"
    claims = verifier.verify(_sign(payload, private_key), now=NOW)

    assert evaluate_entitlement(claims, _context()).code == "unsupported_threshold_period"


def test_version_entitlement_and_support_are_separate(signing_material):
    private_key, verifier = signing_material
    claims = verifier.verify(_sign(_payload("perpetual"), private_key), now=NOW)

    assert claims.support.level == "standard"
    assert evaluate_entitlement(claims, _context(app_major_version="8")).code == "version_not_entitled"


def test_project_identity_is_stable_and_contains_no_path(tmp_path):
    first = ensure_project_identity(tmp_path)
    second = ensure_project_identity(tmp_path)
    manifest = json.loads((tmp_path / ".tech_connector_project").read_text(encoding="utf-8"))

    assert first == second
    assert first.project_id.startswith("prj_")
    assert set(manifest) == {"schema", "project_id", "created_at"}
    assert str(tmp_path) not in json.dumps(manifest)


def test_project_identity_is_stable_across_concurrent_host_creation(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as executor:
        identities = list(executor.map(lambda _index: ensure_project_identity(tmp_path), range(24)))

    assert len({identity.project_id for identity in identities}) == 1


def test_project_identity_refuses_to_overwrite_unknown_schema(tmp_path):
    manifest = tmp_path / ".tech_connector_project"
    manifest.write_text(
        json.dumps({"schema": "tech_connector.project.v999", "project_id": "future"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema is not recognized"):
        ensure_project_identity(tmp_path)
    assert json.loads(manifest.read_text(encoding="utf-8"))["schema"].endswith("v999")


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda payload: payload.update({"sub": "acct_other"}), "principal.account_id"),
        (
            lambda payload: payload["license"].update({"grantee_id": "org_other"}),
            "principal.organization_id",
        ),
        (
            lambda payload: payload["projects"]["authorized"].append(
                dict(payload["projects"]["authorized"][0])
            ),
            "duplicate project_id",
        ),
    ),
)
def test_cross_claim_identity_invariants_are_enforced(signing_material, mutation, message):
    private_key, verifier = signing_material
    payload = _payload()
    mutation(payload)

    with pytest.raises(TokenVerificationError, match=message):
        verifier.verify(_sign(payload, private_key), now=NOW)


def test_installation_identity_is_stable_and_not_a_hardware_fingerprint(tmp_path):
    identity = InstallationDeviceIdentity(tmp_path / "licensing")
    first = identity.device_id_hash()
    second = InstallationDeviceIdentity(tmp_path / "licensing").device_id_hash()
    payload = json.loads((tmp_path / "licensing" / "installation.json").read_text(encoding="utf-8"))

    assert first == second
    assert first.startswith("sha256:")
    assert set(payload) == {"schema", "installation_id"}
    assert not any(key in payload for key in ("hostname", "mac", "cpu", "serial"))


def test_local_licensing_audit_rejects_sensitive_or_creative_metadata(tmp_path):
    sink = FileLicensingAuditSink(tmp_path, clock=lambda: NOW)
    sink.record("device_activated", {"license_id": "lic_test", "activation_id": "act_test"})

    row = json.loads((tmp_path / "licensing_audit.jsonl").read_text(encoding="utf-8"))
    assert row["metadata"] == {"activation_id": "act_test", "license_id": "lic_test"}
    with pytest.raises(ValueError, match="unsupported licensing audit metadata"):
        sink.record("project_registered", {"project_path": "C:/private/film"})
    with pytest.raises(ValueError, match="unsupported licensing audit metadata"):
        sink.record("entitlement_refreshed", {"entitlement_token": "secret"})


def test_verified_token_cache_is_separate_from_general_settings(tmp_path, signing_material):
    private_key, _verifier = signing_material
    context = _runtime_context(tmp_path, private_key)
    payload = _payload("perpetual")
    payload["activation"]["device_id_hash"] = context.device_identity.device_id_hash()
    token = _sign(payload, private_key)

    claims = context.cache_verified_token(token, now=NOW)

    assert claims.license.type is LicenseType.PERPETUAL
    assert context.entitlement_store.load_token() == token
    assert (tmp_path / "licensing" / "entitlement.token").is_file()


def test_missing_cached_entitlement_has_a_user_facing_reason(tmp_path, signing_material):
    private_key, _verifier = signing_material
    context = _runtime_context(tmp_path, private_key)

    evaluation = context.evaluate(
        product="tech_connector",
        app_major_version="7",
        commercial_use=True,
        now=NOW,
    )

    assert not evaluation.decision.allowed
    assert evaluation.decision.code == "missing_entitlement"
    assert evaluation.decision.reason == "No signed entitlement is cached for this installation."


def test_signed_community_entitlement_gates_headless_api_by_project(tmp_path, signing_material):
    private_key, _verifier = signing_material
    context = _runtime_context(tmp_path, private_key)
    identity = ensure_project_identity(tmp_path)
    payload = _payload("community")
    payload["activation"]["device_id_hash"] = context.device_identity.device_id_hash()
    payload["projects"]["authorized"][0]["project_id"] = identity.project_id
    token = _sign(payload, private_key)
    (tmp_path / "licensed_sample.py").write_text("def value():\n    return 42\n", encoding="utf-8")
    api = TechConnectorHeadlessAPI(
        settings={"tech_connector_license_token": token},
        project_root=tmp_path,
        licensing_context=context,
        app_major_version="7",
        commercial_use=True,
    )

    result = api.call_function("licensed_sample.value")

    assert result.ok, result.to_dict()
    assert result.result["value"] == 42
    assert api.entitlement().tier == "community"


def test_signed_community_entitlement_rejects_unregistered_project(tmp_path, signing_material):
    private_key, _verifier = signing_material
    context = _runtime_context(tmp_path, private_key)
    payload = _payload("community")
    payload["activation"]["device_id_hash"] = context.device_identity.device_id_hash()
    token = _sign(payload, private_key)
    api = TechConnectorHeadlessAPI(
        settings={"tech_connector_license_token": token},
        project_root=tmp_path,
        licensing_context=context,
        app_major_version="7",
    )

    result = api.call_function("missing.module")

    assert not result.ok
    assert "project registration" in result.error.lower()


def test_release_validation_rejects_private_signing_keys(tmp_path):
    required = (
        "tech_connector/LICENSE.md",
        "tech_connector/PRIVACY.md",
        "tech_connector/README.md",
        "tech_connector/CONTRIBUTING.md",
        "tech_connector/packaging/requirements-runtime.txt",
    )
    for relative in required:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")
    private_key = tmp_path / "tech_connector" / "config" / "signing.pem"
    private_key.parent.mkdir(parents=True, exist_ok=True)
    private_key.write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="private key"):
        validate_staged_package(tmp_path)
