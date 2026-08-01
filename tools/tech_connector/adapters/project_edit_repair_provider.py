"""Tech Connector project-edit repair adapter for reasoning_runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from reasoning_runtime import (
    RepairContext,
    RepairProposal,
    RepairProvider,
    RepairRecord,
)


class TechConnectorProjectEditRepairProvider(RepairProvider):
    """Delegate concrete source repair while the runtime owns acceptance."""

    name = "tech_connector.project_edit"
    priority = 50

    def supports(self, context: RepairContext) -> bool:
        return bool(
            context.metadata.get("domain") == "project_edit"
            and callable(context.metadata.get("repair_callable"))
        )

    def repair(self, context: RepairContext) -> RepairProposal:
        callback = context.metadata.get("repair_callable")
        if not isinstance(callback, Callable):
            return RepairProposal(candidate=context.candidate, changed=False)
        result = callback(context)
        if isinstance(result, RepairProposal):
            return result
        if not isinstance(result, Mapping):
            return RepairProposal(candidate=context.candidate, changed=False)
        changed = bool(result.get("changed"))
        record = RepairRecord(
            owner=str(result.get("owner") or "project_edit"),
            strategy=str(result.get("strategy") or "domain_provider"),
            model=str(result.get("model") or "deterministic"),
            failure_fingerprint=str(result.get("failure_fingerprint") or ""),
            status="proposed" if changed else "unchanged",
            changed=changed,
            detail=str(result.get("detail") or ""),
        )
        return RepairProposal(
            candidate=result.get("candidate", context.candidate),
            changed=changed,
            records=(record,),
            metadata=dict(result.get("metadata") or {}),
        )
