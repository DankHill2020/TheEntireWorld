"""Tests for monotonic repair acceptance and provider isolation."""

from __future__ import annotations

from typing import Any, Callable

from reasoning_runtime.adapters.repair_provider import (
    RepairContext,
    RepairProposal,
    RepairProvider,
)
from reasoning_runtime.engine.progress_events import ValidationFinding
from reasoning_runtime.reasoning.convergence import ConvergencePolicy, RepairCoordinator


def _finding(
    fingerprint: str,
    *,
    protected: bool = False,
) -> ValidationFinding:
    """Build one deterministic validation finding.

    :param fingerprint: Stable finding identifier.
    :param protected: Whether introducing the finding must block acceptance.
    :return: Validation finding.
    """

    return ValidationFinding(
        category="quality",
        message=fingerprint,
        fingerprint=fingerprint,
        metadata={"protected": protected},
    )


class StubProvider(RepairProvider):
    """Configurable provider used to exercise coordinator boundaries."""

    def __init__(
        self,
        name: str,
        *,
        priority: int,
        supports: Callable[[RepairContext], bool] | None = None,
        repair: Callable[[RepairContext], RepairProposal] | None = None,
    ) -> None:
        self.name = name
        self.priority = priority
        self._supports = supports or (lambda _context: True)
        self._repair = repair or (
            lambda context: RepairProposal(context.candidate, changed=False)
        )

    def supports(self, context: RepairContext) -> bool:
        """Return configured provider support.

        :param context: Repair context.
        :return: Whether this provider supports the context.
        """

        return self._supports(context)

    def repair(self, context: RepairContext) -> RepairProposal:
        """Return the configured repair proposal.

        :param context: Repair context.
        :return: Repair proposal.
        """

        return self._repair(context)


def test_policy_accepts_only_strict_monotonic_progress() -> None:
    """Reject finding swaps even when a proposal resolves one old issue."""

    policy = ConvergencePolicy()
    before = (_finding("a"), _finding("b"))

    accepted = policy.evaluate(before, (_finding("b"),), candidate_changed=True)
    swapped = policy.evaluate(
        before,
        (_finding("b"), _finding("c")),
        candidate_changed=True,
    )

    assert accepted.accepted is True
    assert accepted.resolved == ("a",)
    assert swapped.accepted is False
    assert swapped.status == "non_monotonic"
    assert swapped.resolved == ("a",)
    assert swapped.introduced == ("c",)


def test_policy_rejects_protected_regression() -> None:
    """Reject newly introduced protected findings before count comparison."""

    decision = ConvergencePolicy().evaluate(
        (_finding("a"), _finding("b"), _finding("c")),
        (_finding("b"), _finding("protected", protected=True)),
        candidate_changed=True,
    )

    assert decision.accepted is False
    assert decision.status == "protected_regression"
    assert decision.protected_introductions == ("protected",)


def test_coordinator_skips_broken_provider_and_accepts_next_repair() -> None:
    """Isolate provider exceptions without losing a later valid repair."""

    def fail(_context: RepairContext) -> RepairProposal:
        raise RuntimeError("provider unavailable")

    broken = StubProvider("broken", priority=1, repair=fail)
    working = StubProvider(
        "working",
        priority=2,
        repair=lambda _context: RepairProposal("fixed", changed=True),
    )
    context = RepairContext(
        request="repair",
        candidate="broken",
        findings=(_finding("syntax"),),
    )

    result = RepairCoordinator([working, broken]).attempt(
        context,
        validate=lambda candidate: () if candidate == "fixed" else context.findings,
    )

    assert result.decision.accepted is True
    assert result.provider == "working"
    assert result.candidate == "fixed"
    assert result.repairs[0].owner == "broken"
    assert result.repairs[0].strategy == "provider_repair"
    assert "RuntimeError" in result.repairs[0].detail


def test_coordinator_isolates_validator_failure_and_continues() -> None:
    """Try the next strategy when one candidate cannot be validated."""

    first = StubProvider(
        "invalid-candidate",
        priority=1,
        repair=lambda _context: RepairProposal({"state": "invalid"}, changed=True),
    )
    second = StubProvider(
        "valid-candidate",
        priority=2,
        repair=lambda _context: RepairProposal({"state": "fixed"}, changed=True),
    )
    context = RepairContext(
        request="repair",
        candidate={"state": "broken"},
        findings=(_finding("runtime"),),
    )

    def validate(candidate: Any) -> tuple[ValidationFinding, ...]:
        if candidate["state"] == "invalid":
            raise ValueError("candidate could not be parsed")
        return ()

    result = RepairCoordinator([first, second]).attempt(context, validate=validate)

    assert result.decision.accepted is True
    assert result.provider == "valid-candidate"
    assert result.repairs[0].strategy == "provider_validate"


def test_unchanged_proposal_does_not_run_validator() -> None:
    """Avoid unnecessary or unsafe validation for a no-op proposal."""

    calls = 0
    provider = StubProvider("unchanged", priority=1)
    context = RepairContext(
        request="repair",
        candidate="same",
        findings=(_finding("issue"),),
    )

    def validate(_candidate: Any) -> tuple[ValidationFinding, ...]:
        nonlocal calls
        calls += 1
        return ()

    result = RepairCoordinator([provider]).attempt(context, validate=validate)

    assert calls == 0
    assert result.decision.status == "unchanged"
    assert result.candidate == "same"
