"""Tech Connector domain package for the standalone reasoning runtime.

This module is the compatibility layer that lets ``reasoning_runtime`` install
Tech Connector's DCC/game-development adapters without the runtime importing
Tech Connector directly.
"""

from __future__ import annotations

from typing import Any

from tech_connector.adapters import (
    DccCapabilityBridge,
    DccCodePolicyAdapter,
    DccContextAdapter,
    DccReasoningAdapter,
    DccValidationContract,
    TechConnectorCodeUnderstandingProvider,
    TechConnectorProjectIndexProvider,
    TechConnectorLocalModelEscalationPolicy,
    TechConnectorModelRouter,
    TechConnectorProjectKnowledgeSource,
    TechConnectorRuleProvider,
    TechConnectorProjectEditRepairProvider,
)
from tech_connector.services.symbol_lookup_service import TechConnectorSymbolLookupProvider


class TechConnectorDomainPackage:
    """Factory for Tech Connector adapters consumed by ``ReasoningKernel``."""

    name = "tech_connector"

    def __init__(
        self,
        *,
        app_service: Any = None,
        window: Any = None,
        command_router: Any = None,
        project_root: str = "",
        settings: dict[str, Any] | None = None,
    ) -> None:
        self.app_service = app_service
        self.window = window
        self.command_router = command_router
        self.project_root = project_root
        self.settings = dict(settings) if settings is not None else None

    def get_context_adapters(self) -> list[DccContextAdapter]:
        return [
            DccContextAdapter(
                app_service=self.app_service,
                window=self.window,
                project_root=self.project_root,
            )
        ]

    def get_reasoning_adapters(self) -> list[DccReasoningAdapter]:
        return [DccReasoningAdapter()]

    def get_capability_bridges(self) -> list[DccCapabilityBridge]:
        return [DccCapabilityBridge(command_router=self.command_router)]

    def get_validation_contracts(self) -> list[DccValidationContract]:
        return [DccValidationContract()]

    def get_code_intelligence_adapters(self) -> list[DccCodePolicyAdapter]:
        return [DccCodePolicyAdapter()]

    def get_model_router(self) -> TechConnectorModelRouter:
        return TechConnectorModelRouter(settings=self.settings)

    def get_escalation_policies(self) -> list[TechConnectorLocalModelEscalationPolicy]:
        return [TechConnectorLocalModelEscalationPolicy()]

    def get_code_understanding_providers(self) -> list[TechConnectorCodeUnderstandingProvider]:
        return [TechConnectorCodeUnderstandingProvider()]

    def get_rule_providers(self) -> list[TechConnectorRuleProvider]:
        return [TechConnectorRuleProvider()]

    def get_knowledge_sources(self) -> list[TechConnectorProjectKnowledgeSource]:
        roots = [self.project_root] if self.project_root else []
        return [TechConnectorProjectKnowledgeSource(project_roots=roots)]

    def get_index_providers(self) -> list[TechConnectorProjectIndexProvider]:
        roots = [self.project_root] if self.project_root else []
        return [
            TechConnectorProjectIndexProvider(
                project_roots=roots,
                app_service=self.app_service,
            )
        ]

    def get_symbol_lookup_providers(self) -> list[TechConnectorSymbolLookupProvider]:
        return [TechConnectorSymbolLookupProvider(project_root=self.project_root or None)]

    def get_repair_providers(self) -> list[TechConnectorProjectEditRepairProvider]:
        """Return domain repair implementations governed by runtime convergence."""

        return [TechConnectorProjectEditRepairProvider()]


def create_domain_package(**kwargs: Any) -> TechConnectorDomainPackage:
    return TechConnectorDomainPackage(**kwargs)
