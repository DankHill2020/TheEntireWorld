"""Local entitlement policy evaluation over a previously verified token."""

from __future__ import annotations

from datetime import timezone

from .domain import (
    EntitlementClaims,
    LicenseMarketSegment,
    LicenseType,
    PolicyContext,
    PolicyDecision,
)


def _deny(code: str, reason: str) -> PolicyDecision:
    return PolicyDecision(False, code, reason)


def evaluate_entitlement(claims: EntitlementClaims, context: PolicyContext) -> PolicyDecision:
    """Decide local access without sending project content or filesystem metadata."""
    now = context.now
    if now.tzinfo is None:
        raise ValueError("policy context time must include a timezone")
    now = now.astimezone(timezone.utc)

    if claims.license.status != "active":
        return _deny("license_inactive", "The license is not active.")
    if not claims.principal.email_verified:
        return _deny("email_unverified", "A verified email is required for an official entitlement.")
    if (
        claims.license.market_segment is LicenseMarketSegment.ENTERPRISE
        and "enterprise_use" not in claims.capabilities
    ):
        return _deny(
            "enterprise_capability_missing",
            "This Enterprise entitlement does not include the required enterprise-use capability.",
        )
    if claims.seat_assignment is not None and claims.seat_assignment.status != "active":
        return _deny(
            "seat_assignment_inactive",
            "This named-user seat assignment is not active.",
        )
    if claims.version_entitlement.product != context.product:
        return _deny("wrong_product", "The entitlement was issued for a different product.")
    if now >= claims.expires_at or now >= claims.offline.expires_at:
        return _deny("offline_expired", "Offline access has expired; reconnect to revalidate the license.")
    if claims.activation.device_id_hash != context.device_id_hash:
        return _deny("device_mismatch", "This cached entitlement belongs to a different device activation.")
    if claims.limits.device_limit_per_seat < 1:
        return _deny("invalid_device_limit", "The license has no available device activations.")
    device_limit = (
        claims.limits.device_limit_per_seat
        if claims.seat_assignment is not None
        else claims.limits.seat_count * claims.limits.device_limit_per_seat
    )
    if claims.activation.active_device_count > device_limit:
        return _deny("device_limit_exceeded", "The license currently exceeds its device activation limit.")

    allowed_versions = set(claims.version_entitlement.perpetual_major_versions)
    if allowed_versions and context.app_major_version not in allowed_versions:
        return _deny("version_not_entitled", "This major Tech Connector version is not covered by the license.")

    selected_project = next(
        (item for item in claims.projects.authorized if item.project_id == context.project_id),
        None,
    )
    explicit = claims.projects.authorization_mode == "explicit"
    if context.project_id and explicit and selected_project is None:
        # Community has its own commercial registration policy below. Deferring
        # here both permits genuinely noncommercial projects and returns the
        # more useful registration-specific denial for commercial projects.
        if claims.license.type is not LicenseType.COMMUNITY:
            return _deny(
                "project_not_authorized",
                "The current project is not authorized by this entitlement.",
            )
    if selected_project is not None and selected_project.status != "active":
        return _deny("project_inactive", "The registered project is not active.")

    if claims.license.type is LicenseType.COMMUNITY and context.commercial_use:
        if claims.projects.registration_required and selected_project is None:
            return _deny(
                "project_registration_required",
                "Community commercial use requires project registration.",
            )
        if selected_project is None or not selected_project.commercial_use:
            return _deny(
                "commercial_use_not_authorized",
                "Commercial use is not enabled for this project.",
            )
        if (
            claims.terms is None
            or not selected_project.terms_id
            or selected_project.terms_id != claims.terms.terms_id
        ):
            return _deny(
                "project_terms_missing",
                "Signed community project terms are missing or do not match.",
            )
        if claims.terms.calculation_basis != "adjusted_project_profit":
            return _deny(
                "unsupported_terms_basis",
                "This client does not recognize the signed residual calculation basis.",
            )
        if claims.terms.threshold_period != "project_lifetime":
            return _deny(
                "unsupported_threshold_period",
                "Community profit is measured over the registered project's lifetime.",
            )

    warnings = []
    if now >= claims.offline.refresh_after:
        warnings.append(
            "Online entitlement refresh is due; offline access remains available until its expiration date."
        )
    return PolicyDecision(
        True,
        "allowed",
        "The signed entitlement authorizes this use.",
        tuple(warnings),
        selected_project,
    )
