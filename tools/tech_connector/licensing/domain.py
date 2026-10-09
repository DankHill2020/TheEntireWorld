"""Dependency-free domain models for accounts, licenses, projects, and offline use."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class LicenseType(str, Enum):
    COMMUNITY = "community"
    ANNUAL = "annual"
    PERPETUAL = "perpetual"
    CUSTOM = "custom"


class LicenseMarketSegment(str, Enum):
    """Customer classification, separate from the economic grant model."""

    COMMUNITY = "community"
    INDIE = "indie"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


def parse_timestamp(value: Any, *, field_name: str) -> datetime:
    """Parse an ISO-8601 string or numeric Unix timestamp as an aware UTC datetime."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


@dataclass(frozen=True)
class Principal:
    account_id: str
    email: str
    email_verified: bool
    organization_id: str = ""
    organization_name: str = ""
    organization_role: str = ""
    studio_size_band: str = ""


@dataclass(frozen=True)
class LicenseGrant:
    license_id: str
    type: LicenseType
    status: str
    grantee_type: str
    grantee_id: str
    agreement_version: str
    accepted_at: datetime
    market_segment: LicenseMarketSegment = LicenseMarketSegment.CUSTOM
    offer_id: str = "legacy-v1"
    classification_version: str = "legacy-v1"


@dataclass(frozen=True)
class ProjectAuthorization:
    project_id: str
    status: str = "active"
    commercial_use: bool = False
    terms_id: str = ""


@dataclass(frozen=True)
class ProjectRules:
    registration_required: bool
    authorization_mode: str
    authorized: tuple[ProjectAuthorization, ...] = ()


@dataclass(frozen=True)
class ResidualBracket:
    from_profit_minor: int
    to_profit_minor: int | None
    rate_basis_points: int


@dataclass(frozen=True)
class ResidualTerms:
    terms_id: str
    version: int
    effective_at: datetime
    calculation_basis: str
    currency: str
    profit_threshold_minor: int
    threshold_period: str
    receipts_basis: str
    eligible_cost_standard: str
    owner_labor_standard: str
    related_party_standard: str
    shared_cost_allocation_standard: str
    excluded_cost_categories: tuple[str, ...]
    rate_basis_points: int
    reporting_period: str
    calculation_method: str = "flat_above_threshold"
    residual_brackets: tuple[ResidualBracket, ...] = ()


@dataclass(frozen=True)
class VersionEntitlement:
    product: str
    perpetual_major_versions: tuple[str, ...] = ()
    updates_through: datetime | None = None


@dataclass(frozen=True)
class SupportEntitlement:
    level: str = "none"
    expires_at: datetime | None = None


@dataclass(frozen=True)
class LicenseLimits:
    seat_count: int = 1
    device_limit_per_seat: int = 1


@dataclass(frozen=True)
class SeatAssignment:
    assignment_id: str
    account_id: str
    status: str
    assigned_at: datetime


@dataclass(frozen=True)
class Activation:
    activation_id: str
    device_id_hash: str
    active_device_count: int = 1


@dataclass(frozen=True)
class OfflineWindow:
    refresh_after: datetime
    expires_at: datetime


@dataclass(frozen=True)
class EntitlementClaims:
    schema_version: int
    issuer: str
    audience: tuple[str, ...]
    subject: str
    token_id: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    principal: Principal
    license: LicenseGrant
    projects: ProjectRules
    terms: ResidualTerms | None
    version_entitlement: VersionEntitlement
    support: SupportEntitlement
    limits: LicenseLimits
    seat_assignment: SeatAssignment | None
    activation: Activation
    offline: OfflineWindow
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "EntitlementClaims":
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version not in {1, 2}:
            raise ValueError("unsupported entitlement schema_version")

        principal_data = _mapping(payload.get("principal"), "principal")
        license_data = _mapping(payload.get("license"), "license")
        projects_data = _mapping(payload.get("projects"), "projects")
        version_data = _mapping(payload.get("version_entitlement"), "version_entitlement")
        limits_data = _mapping(payload.get("limits"), "limits")
        activation_data = _mapping(payload.get("activation"), "activation")
        offline_data = _mapping(payload.get("offline"), "offline")
        support_data = _mapping(payload.get("support") or {}, "support")
        raw_seat_assignment = payload.get("seat_assignment")

        license_type_text = _required_text(license_data, "type")
        try:
            license_type = LicenseType(license_type_text)
        except ValueError as exc:
            raise ValueError(f"unsupported license type: {license_type_text}") from exc

        if schema_version == 1:
            market_segment = (
                LicenseMarketSegment.COMMUNITY
                if license_type is LicenseType.COMMUNITY
                else LicenseMarketSegment.CUSTOM
            )
            offer_id = "legacy-v1"
            classification_version = "legacy-v1"
        else:
            market_segment_text = _required_text(license_data, "market_segment")
            try:
                market_segment = LicenseMarketSegment(market_segment_text)
            except ValueError as exc:
                raise ValueError(
                    f"unsupported license market_segment: {market_segment_text}"
                ) from exc
            offer_id = _required_text(license_data, "offer_id")
            classification_version = _required_text(
                license_data,
                "classification_version",
            )

        authorized: list[ProjectAuthorization] = []
        for item in projects_data.get("authorized") or []:
            row = _mapping(item, "projects.authorized[]")
            authorized.append(
                ProjectAuthorization(
                    project_id=_required_text(row, "project_id"),
                    status=str(row.get("status") or "active"),
                    commercial_use=bool(row.get("commercial_use", False)),
                    terms_id=str(row.get("terms_id") or ""),
                )
            )
        project_ids = [item.project_id for item in authorized]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("projects.authorized contains duplicate project_id values")

        authorization_mode = str(projects_data.get("authorization_mode") or "explicit")
        if authorization_mode not in {"explicit", "any"}:
            raise ValueError("projects.authorization_mode must be 'explicit' or 'any'")

        terms = None
        if payload.get("terms") is not None:
            terms_data = _mapping(payload.get("terms"), "terms")
            residual_brackets: list[ResidualBracket] = []
            for item in terms_data.get("residual_brackets") or []:
                row = _mapping(item, "terms.residual_brackets[]")
                upper_value = row.get("to_profit_minor")
                residual_brackets.append(
                    ResidualBracket(
                        from_profit_minor=int(row.get("from_profit_minor") or 0),
                        to_profit_minor=(
                            int(upper_value) if upper_value is not None else None
                        ),
                        rate_basis_points=int(row.get("rate_basis_points") or 0),
                    )
                )
            calculation_method = str(
                terms_data.get("calculation_method")
                or (
                    "marginal_brackets"
                    if residual_brackets
                    else "flat_above_threshold"
                )
            )
            terms = ResidualTerms(
                terms_id=_required_text(terms_data, "terms_id"),
                version=int(terms_data.get("version") or 0),
                effective_at=parse_timestamp(terms_data.get("effective_at"), field_name="terms.effective_at"),
                calculation_basis=_required_text(terms_data, "calculation_basis"),
                currency=_required_text(terms_data, "currency"),
                profit_threshold_minor=int(terms_data.get("profit_threshold_minor") or 0),
                threshold_period=_required_text(terms_data, "threshold_period"),
                receipts_basis=_required_text(terms_data, "receipts_basis"),
                eligible_cost_standard=_required_text(terms_data, "eligible_cost_standard"),
                owner_labor_standard=_required_text(terms_data, "owner_labor_standard"),
                related_party_standard=_required_text(terms_data, "related_party_standard"),
                shared_cost_allocation_standard=_required_text(
                    terms_data, "shared_cost_allocation_standard"
                ),
                excluded_cost_categories=tuple(
                    str(item) for item in terms_data.get("excluded_cost_categories") or [] if item
                ),
                rate_basis_points=int(terms_data.get("rate_basis_points") or 0),
                reporting_period=_required_text(terms_data, "reporting_period"),
                calculation_method=calculation_method,
                residual_brackets=tuple(residual_brackets),
            )
            if terms.version < 1:
                raise ValueError("terms.version must be positive")
            if terms.profit_threshold_minor < 0:
                raise ValueError("terms.profit_threshold_minor cannot be negative")
            if not 0 <= terms.rate_basis_points <= 10_000:
                raise ValueError("terms.rate_basis_points must be between 0 and 10000")
            if terms.calculation_method not in {
                "flat_above_threshold",
                "marginal_brackets",
            }:
                raise ValueError("unsupported terms.calculation_method")
            if terms.calculation_method == "flat_above_threshold":
                if terms.residual_brackets:
                    raise ValueError(
                        "flat_above_threshold terms cannot contain residual_brackets"
                    )
            else:
                if not terms.residual_brackets:
                    raise ValueError(
                        "marginal_brackets terms require residual_brackets"
                    )
                expected_lower = terms.profit_threshold_minor
                previous_rate = -1
                for index, bracket in enumerate(terms.residual_brackets):
                    if bracket.from_profit_minor != expected_lower:
                        raise ValueError(
                            "terms.residual_brackets must be contiguous from the profit threshold"
                        )
                    if not 0 <= bracket.rate_basis_points <= 10_000:
                        raise ValueError(
                            "terms.residual_brackets rate_basis_points must be between 0 and 10000"
                        )
                    if bracket.rate_basis_points < previous_rate:
                        raise ValueError(
                            "terms.residual_brackets rates must not decrease"
                        )
                    previous_rate = bracket.rate_basis_points
                    is_last = index == len(terms.residual_brackets) - 1
                    if bracket.to_profit_minor is None:
                        if not is_last:
                            raise ValueError(
                                "only the final residual bracket may be open-ended"
                            )
                    else:
                        if bracket.to_profit_minor <= bracket.from_profit_minor:
                            raise ValueError(
                                "residual bracket upper bound must exceed its lower bound"
                            )
                        expected_lower = bracket.to_profit_minor
                        if is_last:
                            raise ValueError(
                                "the final residual bracket must be open-ended"
                            )

        raw_audience = payload.get("aud")
        audience = (raw_audience,) if isinstance(raw_audience, str) else tuple(raw_audience or ())
        if not audience or not all(isinstance(item, str) and item for item in audience):
            raise ValueError("aud must contain at least one audience")

        update_value = version_data.get("updates_through")
        support_expiry = support_data.get("expires_at")
        seat_count = int(limits_data.get("seat_count") or 0)
        device_limit = int(limits_data.get("device_limit_per_seat") or 0)
        active_device_count = int(activation_data.get("active_device_count") or 0)
        if seat_count < 1 or device_limit < 1 or active_device_count < 1:
            raise ValueError("seat and device limits must be valid positive counts")
        seat_assignment = None
        if raw_seat_assignment is not None:
            seat_data = _mapping(raw_seat_assignment, "seat_assignment")
            seat_assignment = SeatAssignment(
                assignment_id=_required_text(seat_data, "assignment_id"),
                account_id=_required_text(seat_data, "account_id"),
                status=_required_text(seat_data, "status"),
                assigned_at=parse_timestamp(
                    seat_data.get("assigned_at"),
                    field_name="seat_assignment.assigned_at",
                ),
            )

        claims = cls(
            schema_version=schema_version,
            issuer=_required_text(payload, "iss"),
            audience=audience,
            subject=_required_text(payload, "sub"),
            token_id=_required_text(payload, "jti"),
            issued_at=parse_timestamp(payload.get("iat"), field_name="iat"),
            not_before=parse_timestamp(payload.get("nbf"), field_name="nbf"),
            expires_at=parse_timestamp(payload.get("exp"), field_name="exp"),
            principal=Principal(
                account_id=_required_text(principal_data, "account_id"),
                email=_required_text(principal_data, "email"),
                email_verified=bool(principal_data.get("email_verified", False)),
                organization_id=str(principal_data.get("organization_id") or ""),
                organization_name=str(principal_data.get("organization_name") or ""),
                organization_role=str(principal_data.get("organization_role") or ""),
                studio_size_band=str(principal_data.get("studio_size_band") or ""),
            ),
            license=LicenseGrant(
                license_id=_required_text(license_data, "license_id"),
                type=license_type,
                status=_required_text(license_data, "status"),
                grantee_type=_required_text(license_data, "grantee_type"),
                grantee_id=_required_text(license_data, "grantee_id"),
                agreement_version=_required_text(license_data, "agreement_version"),
                accepted_at=parse_timestamp(
                    license_data.get("accepted_at"), field_name="license.accepted_at"
                ),
                market_segment=market_segment,
                offer_id=offer_id,
                classification_version=classification_version,
            ),
            projects=ProjectRules(
                registration_required=bool(projects_data.get("registration_required", False)),
                authorization_mode=authorization_mode,
                authorized=tuple(authorized),
            ),
            terms=terms,
            version_entitlement=VersionEntitlement(
                product=_required_text(version_data, "product"),
                perpetual_major_versions=tuple(
                    str(item)
                    for item in version_data.get("perpetual_major_versions") or []
                ),
                updates_through=(
                    parse_timestamp(
                        update_value,
                        field_name="version_entitlement.updates_through",
                    )
                    if update_value
                    else None
                ),
            ),
            support=SupportEntitlement(
                level=str(support_data.get("level") or "none"),
                expires_at=(
                    parse_timestamp(support_expiry, field_name="support.expires_at")
                    if support_expiry
                    else None
                ),
            ),
            limits=LicenseLimits(
                seat_count=seat_count,
                device_limit_per_seat=device_limit,
            ),
            seat_assignment=seat_assignment,
            activation=Activation(
                activation_id=_required_text(activation_data, "activation_id"),
                device_id_hash=_required_text(activation_data, "device_id_hash"),
                active_device_count=active_device_count,
            ),
            offline=OfflineWindow(
                refresh_after=parse_timestamp(offline_data.get("refresh_after"), field_name="offline.refresh_after"),
                expires_at=parse_timestamp(offline_data.get("expires_at"), field_name="offline.expires_at"),
            ),
            capabilities=tuple(sorted({str(item) for item in payload.get("capabilities") or [] if item})),
        )
        if claims.subject != claims.principal.account_id:
            raise ValueError("sub must match principal.account_id")
        if (
            claims.seat_assignment is not None
            and claims.seat_assignment.account_id != claims.principal.account_id
        ):
            raise ValueError("seat_assignment.account_id must match principal.account_id")
        if claims.license.grantee_type == "individual":
            if claims.license.grantee_id != claims.principal.account_id:
                raise ValueError("individual license grantee_id must match principal.account_id")
        elif claims.license.grantee_type == "organization":
            if (
                not claims.principal.organization_id
                or claims.license.grantee_id != claims.principal.organization_id
            ):
                raise ValueError(
                    "organization license grantee_id must match principal.organization_id"
                )
        else:
            raise ValueError("license.grantee_type must be 'individual' or 'organization'")
        if schema_version >= 2:
            if (
                claims.license.market_segment is LicenseMarketSegment.COMMUNITY
                and claims.license.type is not LicenseType.COMMUNITY
            ):
                raise ValueError("community market_segment requires a community license type")
            if claims.license.market_segment is LicenseMarketSegment.ENTERPRISE:
                if claims.license.type is LicenseType.COMMUNITY:
                    raise ValueError("enterprise market_segment cannot use a community license type")
                if claims.license.grantee_type != "organization":
                    raise ValueError("enterprise market_segment requires an organization grantee")
            if (
                claims.license.market_segment
                in {LicenseMarketSegment.INDIE, LicenseMarketSegment.ENTERPRISE}
                and not claims.principal.studio_size_band
            ):
                raise ValueError(
                    "indie and enterprise entitlements require principal.studio_size_band"
                )
            if (
                claims.license.market_segment
                in {LicenseMarketSegment.INDIE, LicenseMarketSegment.ENTERPRISE}
                and claims.seat_assignment is None
            ):
                raise ValueError(
                    "indie and enterprise entitlements require a named-user seat_assignment"
                )
        if claims.offline.refresh_after >= claims.offline.expires_at:
            raise ValueError("offline.refresh_after must be before offline.expires_at")
        return claims


@dataclass(frozen=True)
class PolicyContext:
    now: datetime
    product: str
    app_major_version: str
    project_id: str = ""
    commercial_use: bool = False
    device_id_hash: str = ""


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str
    warnings: tuple[str, ...] = ()
    project: ProjectAuthorization | None = None


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    created_at: datetime
    schema: str = field(default="tech_connector.project.v2", init=False)
