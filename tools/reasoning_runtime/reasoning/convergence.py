"""Generic monotonic validation and repair convergence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable

from reasoning_runtime.adapters.repair_provider import (
    RepairContext,
    RepairProposal,
    RepairProvider,
)
if TYPE_CHECKING:
    from reasoning_runtime.engine.progress_events import RepairRecord, ValidationFinding


FindingPredicate = Callable[["ValidationFinding"], bool]
CandidateValidator = Callable[[Any], Iterable["ValidationFinding"]]


def _finding_key(finding: "ValidationFinding") -> str:
    return finding.fingerprint or "|".join(
        (
            finding.category,
            finding.path,
            finding.owner,
            finding.message,
        )
    )


@dataclass(frozen=True)
class ConvergenceDecision:
    """Observable decision for one candidate transition."""

    accepted: bool
    status: str
    summary: str
    before_count: int
    after_count: int
    resolved: tuple[str, ...] = ()
    introduced: tuple[str, ...] = ()
    protected_introductions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConvergenceResult:
    """Result of trying registered providers against one validation snapshot."""

    candidate: Any
    findings: tuple["ValidationFinding", ...]
    repairs: tuple["RepairRecord", ...]
    decision: ConvergenceDecision
    provider: str = ""


class ConvergencePolicy:
    """Accept only candidate transitions that make proven monotonic progress."""

    def evaluate(
        self,
        before: Iterable["ValidationFinding"],
        after: Iterable["ValidationFinding"],
        *,
        candidate_changed: bool,
        is_protected: FindingPredicate | None = None,
    ) -> ConvergenceDecision:
        before_by_key = {_finding_key(item): item for item in before}
        after_by_key = {_finding_key(item): item for item in after}
        resolved = tuple(sorted(set(before_by_key) - set(after_by_key)))
        introduced = tuple(sorted(set(after_by_key) - set(before_by_key)))
        protected = tuple(
            key
            for key in introduced
            if (
                bool(after_by_key[key].metadata.get("protected"))
                or bool(is_protected and is_protected(after_by_key[key]))
            )
        )

        accepted = bool(
            candidate_changed
            and resolved
            and len(after_by_key) < len(before_by_key)
            and not protected
        )
        if accepted:
            status = "accepted"
            summary = (
                f"Accepted monotonic repair: {len(before_by_key)} -> "
                f"{len(after_by_key)} finding(s); resolved {len(resolved)}."
            )
        elif not candidate_changed:
            status = "unchanged"
            summary = "Rejected repair because the candidate did not change."
        elif protected:
            status = "protected_regression"
            summary = (
                "Rejected repair because it introduced protected finding(s): "
                + ", ".join(protected)
            )
        elif not resolved:
            status = "no_progress"
            summary = "Rejected repair because it resolved no existing finding."
        else:
            status = "non_monotonic"
            summary = (
                f"Rejected non-monotonic repair: {len(before_by_key)} -> "
                f"{len(after_by_key)} finding(s)."
            )
        return ConvergenceDecision(
            accepted=accepted,
            status=status,
            summary=summary,
            before_count=len(before_by_key),
            after_count=len(after_by_key),
            resolved=resolved,
            introduced=introduced,
            protected_introductions=protected,
        )


class RepairCoordinator:
    """Run domain providers while retaining runtime-owned acceptance policy."""

    def __init__(
        self,
        providers: Iterable[RepairProvider] = (),
        *,
        policy: ConvergencePolicy | None = None,
    ) -> None:
        self.providers = list(providers)
        self.policy = policy or ConvergencePolicy()

    def register(self, provider: RepairProvider) -> None:
        self.providers.append(provider)

    def attempt(
        self,
        context: RepairContext,
        *,
        validate: CandidateValidator,
        is_protected: FindingPredicate | None = None,
    ) -> ConvergenceResult:
        providers = sorted(self.providers, key=lambda item: item.priority)
        last_decision = self.policy.evaluate(
            context.findings,
            context.findings,
            candidate_changed=False,
            is_protected=is_protected,
        )
        records: list["RepairRecord"] = []
        for provider in providers:
            try:
                supported = provider.supports(context)
            except Exception as exc:
                records.append(self._provider_error_record(provider, "supports", exc))
                last_decision = self._provider_error_decision(context, provider, exc)
                continue
            if not supported:
                continue
            try:
                proposal: RepairProposal = provider.repair(context)
            except Exception as exc:
                records.append(self._provider_error_record(provider, "repair", exc))
                last_decision = self._provider_error_decision(context, provider, exc)
                continue
            records.extend(proposal.records)
            if not proposal.changed:
                last_decision = self.policy.evaluate(
                    context.findings,
                    context.findings,
                    candidate_changed=False,
                    is_protected=is_protected,
                )
                continue
            try:
                after = tuple(validate(proposal.candidate))
            except Exception as exc:
                records.append(self._provider_error_record(provider, "validate", exc))
                last_decision = self._provider_error_decision(context, provider, exc)
                continue
            decision = self.policy.evaluate(
                context.findings,
                after,
                candidate_changed=proposal.changed,
                is_protected=is_protected,
            )
            last_decision = decision
            if decision.accepted:
                return ConvergenceResult(
                    candidate=proposal.candidate,
                    findings=after,
                    repairs=tuple(records),
                    decision=decision,
                    provider=provider.name,
                )
        return ConvergenceResult(
            candidate=context.candidate,
            findings=context.findings,
            repairs=tuple(records),
            decision=last_decision,
        )

    @staticmethod
    def _provider_error_record(
        provider: RepairProvider,
        phase: str,
        error: Exception,
    ) -> "RepairRecord":
        """Build an observable record for an isolated provider failure.

        :param provider: Failing repair provider.
        :param phase: Provider lifecycle phase.
        :param error: Raised exception.
        :return: Failed repair record.
        """

        from reasoning_runtime.engine.progress_events import RepairRecord

        return RepairRecord(
            owner=str(provider.name or provider.__class__.__name__),
            strategy=f"provider_{phase}",
            status="failed",
            changed=False,
            detail=f"{type(error).__name__}: {error}"[:1000],
        )

    @staticmethod
    def _provider_error_decision(
        context: RepairContext,
        provider: RepairProvider,
        error: Exception,
    ) -> ConvergenceDecision:
        """Build a nonterminal decision for an isolated provider failure.

        :param context: Current repair context.
        :param provider: Failing repair provider.
        :param error: Raised exception.
        :return: Observable provider-error decision.
        """

        count = len({_finding_key(item) for item in context.findings})
        return ConvergenceDecision(
            accepted=False,
            status="provider_error",
            summary=(
                f"Repair provider {provider.name!r} failed without aborting "
                f"convergence: {type(error).__name__}: {error}"
            )[:1200],
            before_count=count,
            after_count=count,
        )
