"""Tech Connector license login, verification, and entitlement helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable


LICENSE_TOKEN_PREFIX = "tc1"
DEFAULT_REVENUE_THRESHOLD_USD = 500_000

TIER_CAPABILITIES = {
    "community": {
        "local_use",
        "personal_outputs",
        "community_contributions",
    },
    "personal": {
        "local_use",
        "personal_outputs",
        "community_contributions",
        "small_studio_commercial_grace",
        "official_api_access",
    },
    "commercial": {
        "local_use",
        "personal_outputs",
        "community_contributions",
        "commercial_use",
        "small_studio_commercial_grace",
        "official_api_access",
        "royalty_reporting",
        "full_automation",
    },
    "enterprise": {
        "local_use",
        "personal_outputs",
        "community_contributions",
        "commercial_use",
        "enterprise_pipeline",
        "official_api_access",
        "team_seats",
        "royalty_reporting",
        "full_automation",
    },
}


@dataclass(frozen=True)
class LicenseEntitlement:
    unlocked: bool
    tier: str
    account_email: str = ""
    account_id: str = ""
    organization: str = ""
    license_id: str = ""
    source: str = "none"
    reason: str = ""
    expires_at: str = ""
    revenue_threshold_usd: int = DEFAULT_REVENUE_THRESHOLD_USD
    royalty_percent: float = 2.0
    royalty_cap_percent: float = 3.0
    capabilities: tuple[str, ...] = ()
    resale_allowed: bool = False
    redistribution_allowed: bool = False
    hosted_access_allowed: bool = False
    ai_training_allowed: bool = False
    direct_code_reuse_allowed: bool = False
    official_api_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        return data


def _b64url_decode(value: str) -> bytes:
    value = value.strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_tier(value: str) -> str:
    tier = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "free": "personal",
        "individual": "personal",
        "creator": "personal",
        "small_studio": "commercial",
        "business": "commercial",
        "company": "commercial",
        "org": "enterprise",
    }
    tier = aliases.get(tier, tier)
    return tier if tier in TIER_CAPABILITIES else "community"


def make_license_token(payload: dict[str, Any], secret: str) -> str:
    """Create a signed token for tests/dev tooling.

    Production tokens should be issued by the licensing service, not by the
    desktop app. The verifier intentionally only needs the shared verification
    secret passed by deployment/test code.
    """
    body = dict(payload)
    body.setdefault("version", 1)
    encoded = _b64url_encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{LICENSE_TOKEN_PREFIX}.{encoded}.{_b64url_encode(signature)}"


def verify_license_token(
    token: str,
    *,
    secret: str | None = None,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any], str]:
    token = str(token or "").strip()
    if not token:
        return False, {}, "No license token saved."
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_TOKEN_PREFIX:
        return False, {}, "License token format is not recognized."
    secret = secret or os.environ.get("TECH_CONNECTOR_LICENSE_VERIFY_SECRET", "")
    if not secret:
        return False, {}, "License verification secret is not configured."
    encoded_payload, encoded_signature = parts[1], parts[2]
    expected = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    try:
        received = _b64url_decode(encoded_signature)
    except Exception:
        return False, {}, "License token signature is invalid."
    if not hmac.compare_digest(expected, received):
        return False, {}, "License token signature did not verify."
    try:
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    except Exception:
        return False, {}, "License token payload is invalid."
    expires = _parse_datetime(str(payload.get("expires_at") or ""))
    if expires and expires <= (now or _utc_now()):
        return False, payload, "License token has expired."
    if bool(payload.get("revoked", False)):
        return False, payload, "License token has been revoked."
    return True, payload, "License token verified."


def entitlement_from_payload(payload: dict[str, Any], *, source: str, reason: str) -> LicenseEntitlement:
    tier = _normalize_tier(str(payload.get("tier") or payload.get("plan") or "community"))
    capabilities = set(TIER_CAPABILITIES.get(tier, TIER_CAPABILITIES["community"]))
    capabilities.update(str(item) for item in payload.get("features") or [] if item)
    capabilities.discard("resale")
    capabilities.discard("redistribution")
    capabilities.discard("hosted_access")
    return LicenseEntitlement(
        unlocked=True,
        tier=tier,
        account_email=str(payload.get("email") or payload.get("account_email") or ""),
        account_id=str(payload.get("sub") or payload.get("account_id") or ""),
        organization=str(payload.get("organization") or ""),
        license_id=str(payload.get("license_id") or ""),
        source=source,
        reason=reason,
        expires_at=str(payload.get("expires_at") or ""),
        revenue_threshold_usd=int(payload.get("revenue_threshold_usd") or DEFAULT_REVENUE_THRESHOLD_USD),
        royalty_percent=float(payload.get("royalty_percent") or 2.0),
        royalty_cap_percent=float(payload.get("royalty_cap_percent") or 3.0),
        capabilities=tuple(sorted(capabilities)),
        resale_allowed=False,
        redistribution_allowed=bool(payload.get("redistribution_allowed", False)),
        hosted_access_allowed=bool(payload.get("hosted_access_allowed", False)),
        ai_training_allowed=False,
        direct_code_reuse_allowed=False,
        official_api_required=True,
    )


def verify_entitlement(
    settings: dict[str, Any],
    *,
    token_verifier: Callable[[str], tuple[bool, dict[str, Any], str]] | None = None,
    secret: str | None = None,
    now: datetime | None = None,
) -> LicenseEntitlement:
    """Verify the user's current entitlement from saved login/license settings."""
    token = str(settings.get("tech_connector_license_token") or os.environ.get("TECH_CONNECTOR_LICENSE_TOKEN") or "").strip()
    email = str(settings.get("tech_connector_account_email") or "").strip()
    require_login = bool(settings.get("tech_connector_require_login", True))
    allow_offline_community = bool(settings.get("tech_connector_allow_offline_community", False))
    if token:
        verifier = token_verifier or (lambda value: verify_license_token(value, secret=secret, now=now))
        ok, payload, reason = verifier(token)
        if ok:
            return entitlement_from_payload(payload, source="license_token", reason=reason)
        return LicenseEntitlement(
            unlocked=False,
            tier="locked",
            account_email=email or str(payload.get("email") or ""),
            license_id=str(payload.get("license_id") or ""),
            source="license_token",
            reason=reason,
            capabilities=(),
        )
    if email and not require_login:
        return entitlement_from_payload({"tier": "personal", "email": email}, source="local_account", reason="Local account email accepted by policy.")
    if allow_offline_community:
        return entitlement_from_payload({"tier": "community", "email": email}, source="offline_community", reason="Offline community mode is enabled.")
    return LicenseEntitlement(
        unlocked=False,
        tier="locked",
        account_email=email,
        source="none",
        reason="Login or license verification is required.",
        capabilities=(),
    )


def update_license_login(settings: dict[str, Any], *, email: str = "", token: str = "") -> dict[str, Any]:
    if email:
        settings["tech_connector_account_email"] = email.strip()
    if token:
        settings["tech_connector_license_token"] = token.strip()
    return entitlement_status_row(settings)


def clear_license_login(settings: dict[str, Any]) -> dict[str, Any]:
    settings["tech_connector_account_email"] = ""
    settings["tech_connector_license_token"] = ""
    return entitlement_status_row(settings)


def entitlement_status_row(settings: dict[str, Any], **verify_kwargs: Any) -> dict[str, Any]:
    entitlement = verify_entitlement(settings, **verify_kwargs)
    label = entitlement.tier.title() if entitlement.unlocked else "Locked"
    account = entitlement.account_email or entitlement.organization or entitlement.license_id
    mode = f"{label} ({account})" if account else label
    return {
        "id": "tech_connector_license",
        "name": "Tech Connector License",
        "category": "License",
        "connected": entitlement.unlocked,
        "configured": bool(settings.get("tech_connector_license_token") or settings.get("tech_connector_account_email")),
        "mode": mode,
        "tier": entitlement.tier,
        "capabilities": list(entitlement.capabilities),
        "reason": entitlement.reason,
        "resale_allowed": entitlement.resale_allowed,
        "redistribution_allowed": entitlement.redistribution_allowed,
        "hosted_access_allowed": entitlement.hosted_access_allowed,
        "ai_training_allowed": entitlement.ai_training_allowed,
        "direct_code_reuse_allowed": entitlement.direct_code_reuse_allowed,
        "official_api_required": entitlement.official_api_required,
        "entitlement": entitlement.to_dict(),
        "summary": f"Tech Connector License: {mode} - {entitlement.reason}",
    }


def requires_commercial_license(
    settings: dict[str, Any],
    *,
    annual_attributable_revenue_usd: int,
    **verify_kwargs: Any,
) -> bool:
    entitlement = verify_entitlement(settings, **verify_kwargs)
    if not entitlement.unlocked:
        return True
    if "enterprise_pipeline" in entitlement.capabilities or "commercial_use" in entitlement.capabilities:
        return False
    return int(annual_attributable_revenue_usd or 0) >= entitlement.revenue_threshold_usd
