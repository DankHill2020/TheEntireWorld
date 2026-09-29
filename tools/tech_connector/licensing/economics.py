"""Deterministic residual estimates from already accepted signed terms."""

from __future__ import annotations

from .domain import ResidualTerms


def _round_basis_points(numerator: int) -> int:
    """Round a non-negative minor-unit × basis-point value half up."""
    return (int(numerator) + 5_000) // 10_000


def estimate_residual_minor(
    terms: ResidualTerms,
    adjusted_project_profit_minor: int,
) -> int:
    """Estimate residual minor units; backend accounting remains authoritative."""
    profit = max(0, int(adjusted_project_profit_minor))
    if profit <= terms.profit_threshold_minor:
        return 0
    if terms.calculation_method == "flat_above_threshold":
        taxable = profit - terms.profit_threshold_minor
        return _round_basis_points(taxable * terms.rate_basis_points)

    numerator = 0
    for bracket in terms.residual_brackets:
        if profit <= bracket.from_profit_minor:
            break
        upper = (
            profit
            if bracket.to_profit_minor is None
            else min(profit, bracket.to_profit_minor)
        )
        taxable = max(0, upper - bracket.from_profit_minor)
        numerator += taxable * bracket.rate_basis_points
        if bracket.to_profit_minor is None or profit <= bracket.to_profit_minor:
            break
    return _round_basis_points(numerator)
