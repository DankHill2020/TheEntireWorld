"""Shared, privacy-conscious licensing primitives for Tech Connector clients."""

from .acceptance import FileLicenseAcceptanceStore
from .domain import (
    EntitlementClaims,
    LicenseMarketSegment,
    LicenseType,
    PolicyContext,
    PolicyDecision,
    ProjectIdentity,
    ResidualBracket,
    SeatAssignment,
)
from .context import LicensingContext, LicensingEvaluation
from .economics import estimate_residual_minor
from .policy import evaluate_entitlement
from .products import (
    CORE_PRODUCT_ID,
    OFFICIAL_TOOLS_PRODUCT_ID,
    ProductAccessDecision,
    evaluate_product_access,
)
from .project_identity import ensure_project_identity, load_project_identity
from .verification import EntitlementTokenVerifier, TokenVerificationError

__all__ = [
    "EntitlementClaims",
    "EntitlementTokenVerifier",
    "FileLicenseAcceptanceStore",
    "LicenseMarketSegment",
    "LicenseType",
    "LicensingContext",
    "LicensingEvaluation",
    "PolicyContext",
    "PolicyDecision",
    "ProductAccessDecision",
    "ProjectIdentity",
    "ResidualBracket",
    "SeatAssignment",
    "TokenVerificationError",
    "CORE_PRODUCT_ID",
    "OFFICIAL_TOOLS_PRODUCT_ID",
    "ensure_project_identity",
    "estimate_residual_minor",
    "evaluate_entitlement",
    "evaluate_product_access",
    "load_project_identity",
]
