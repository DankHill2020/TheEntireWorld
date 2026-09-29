"""Product-capability checks layered on top of a valid Core entitlement."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import EntitlementClaims


CORE_PRODUCT_ID = "tech_connector.core"
OFFICIAL_TOOLS_PRODUCT_ID = "official_tools_bundle"


@dataclass(frozen=True)
class ProductAccessDecision:
    product_id: str
    allowed: bool
    code: str
    reason: str


def evaluate_product_access(
    claims: EntitlementClaims | None,
    product_id: str,
) -> ProductAccessDecision:
    """Evaluate an optional product without changing the Core startup policy."""
    requested = str(product_id or "").strip()
    if requested == CORE_PRODUCT_ID:
        return ProductAccessDecision(
            requested,
            claims is not None,
            "allowed" if claims is not None else "core_entitlement_required",
            (
                "The signed entitlement authorizes Tech Connector Core."
                if claims is not None
                else "Tech Connector Core requires a valid signed entitlement."
            ),
        )
    if claims is None:
        return ProductAccessDecision(
            requested,
            False,
            "entitlement_required",
            "A valid signed entitlement is required for this product.",
        )
    if requested not in set(claims.capabilities):
        return ProductAccessDecision(
            requested,
            False,
            "product_capability_missing",
            f"The signed entitlement does not include '{requested}'.",
        )
    return ProductAccessDecision(
        requested,
        True,
        "allowed",
        f"The signed entitlement includes '{requested}'.",
    )
