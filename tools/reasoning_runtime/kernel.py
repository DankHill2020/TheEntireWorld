"""Small standalone kernel for registering and running domain adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reasoning_runtime.adapters.capability_bridge import CapabilityBridge, ToolSpec
from reasoning_runtime.adapters.code_intelligence_adapter import CodeIntelligenceAdapter
from reasoning_runtime.adapters.context_adapter import ContextAdapter, InteractionSurface
from reasoning_runtime.models import EscalationPolicy
from reasoning_runtime.adapters.evidence_policy import EvidencePolicy
from reasoning_runtime.adapters.reasoning_adapter import ReasoningAdapter
from reasoning_runtime.adapters.validation_contract import ValidationContract, ValidationReport
from reasoning_runtime.adapters.repair_provider import RepairProvider
from reasoning_runtime.components.action_planning import ActionPlanner
from reasoning_runtime.components.code_understanding import CodeUnderstandingBroker, CodeUnderstandingProvider
from reasoning_runtime.components.knowledge import KnowledgeBroker, KnowledgeSource
from reasoning_runtime.components.indexing import IndexProvider, IndexRegistry
from reasoning_runtime.components.symbol_lookup import SymbolLookupBroker, SymbolLookupProvider
from reasoning_runtime.models import ModelRequest, ModelRoute, ModelRouter, StaticModelRouter
from reasoning_runtime.components.rules import RuleProvider, RuleSet
from reasoning_runtime.reasoning.layers import LayeredReasoningPipeline, ReasoningLayer, ReasoningLayerResult
from reasoning_runtime.reasoning.convergence import RepairCoordinator


@dataclass(frozen=True)
class KernelRunResult:
    ok: bool
    context: dict[str, Any] = field(default_factory=dict)
    interaction_surface: InteractionSurface = field(default_factory=InteractionSurface)
    system_instructions: tuple[str, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    validation: tuple[ValidationReport, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    model_route: ModelRoute | None = None
    rule_sets: tuple[RuleSet, ...] = ()
    reasoning_result: ReasoningLayerResult | None = None


class ReasoningKernel:
    """Coordinates domain adapters without importing any domain package."""

    def __init__(self) -> None:
        self.context_adapters: list[ContextAdapter] = []
        self.reasoning_adapters: list[ReasoningAdapter] = []
        self.capability_bridges: list[CapabilityBridge] = []
        self.validation_contracts: list[ValidationContract] = []
        self.evidence_policies: list[EvidencePolicy] = []
        self.escalation_policies: list[EscalationPolicy] = []
        self.code_intelligence_adapters: list[CodeIntelligenceAdapter] = []
        self.model_router: ModelRouter = StaticModelRouter()
        self.code_understanding_providers: list[CodeUnderstandingProvider] = []
        self.rule_providers: list[RuleProvider] = []
        self.knowledge_sources: list[KnowledgeSource] = []
        self.index_providers: list[IndexProvider] = []
        self.symbol_lookup_providers: list[SymbolLookupProvider] = []
        self.action_planners: list[ActionPlanner] = []
        self.repair_providers: list[RepairProvider] = []
        self.reasoning_pipeline = LayeredReasoningPipeline()

    def register_context_adapter(self, adapter: ContextAdapter) -> None:
        self.context_adapters.append(adapter)

    def register_reasoning_adapter(self, adapter: ReasoningAdapter) -> None:
        self.reasoning_adapters.append(adapter)

    def register_capability_bridge(self, bridge: CapabilityBridge) -> None:
        self.capability_bridges.append(bridge)

    def register_validation_contract(self, contract: ValidationContract) -> None:
        self.validation_contracts.append(contract)

    def register_evidence_policy(self, policy: EvidencePolicy) -> None:
        self.evidence_policies.append(policy)

    def register_escalation_policy(self, policy: EscalationPolicy) -> None:
        self.escalation_policies.append(policy)

    def register_code_intelligence_adapter(self, adapter: CodeIntelligenceAdapter) -> None:
        self.code_intelligence_adapters.append(adapter)

    def register_model_router(self, router: ModelRouter) -> None:
        self.model_router = router

    def register_code_understanding_provider(self, provider: CodeUnderstandingProvider) -> None:
        self.code_understanding_providers.append(provider)

    def register_rule_provider(self, provider: RuleProvider) -> None:
        self.rule_providers.append(provider)

    def register_knowledge_source(self, source: KnowledgeSource) -> None:
        self.knowledge_sources.append(source)

    def register_index_provider(self, provider: IndexProvider) -> None:
        self.index_providers.append(provider)

    def register_symbol_lookup_provider(self, provider: SymbolLookupProvider) -> None:
        self.symbol_lookup_providers.append(provider)

    def register_action_planner(self, planner: ActionPlanner) -> None:
        self.action_planners.append(planner)

    def register_repair_provider(self, provider: RepairProvider) -> None:
        self.repair_providers.append(provider)

    def register_reasoning_layer(self, layer: ReasoningLayer) -> None:
        self.reasoning_pipeline.register(layer)

    def install(self, domain_package: Any) -> None:
        """Install adapters returned by a domain package."""

        for adapter in getattr(domain_package, "get_context_adapters", lambda: [])():
            self.register_context_adapter(adapter)
        for adapter in getattr(domain_package, "get_reasoning_adapters", lambda: [])():
            self.register_reasoning_adapter(adapter)
        for bridge in getattr(domain_package, "get_capability_bridges", lambda: [])():
            self.register_capability_bridge(bridge)
        for contract in getattr(domain_package, "get_validation_contracts", lambda: [])():
            self.register_validation_contract(contract)
        for policy in getattr(domain_package, "get_evidence_policies", lambda: [])():
            self.register_evidence_policy(policy)
        for policy in getattr(domain_package, "get_escalation_policies", lambda: [])():
            self.register_escalation_policy(policy)
        for adapter in getattr(domain_package, "get_code_intelligence_adapters", lambda: [])():
            self.register_code_intelligence_adapter(adapter)
        router = getattr(domain_package, "get_model_router", lambda: None)()
        if router is not None:
            self.register_model_router(router)
        for provider in getattr(domain_package, "get_code_understanding_providers", lambda: [])():
            self.register_code_understanding_provider(provider)
        for provider in getattr(domain_package, "get_rule_providers", lambda: [])():
            self.register_rule_provider(provider)
        for source in getattr(domain_package, "get_knowledge_sources", lambda: [])():
            self.register_knowledge_source(source)
        for provider in getattr(domain_package, "get_index_providers", lambda: [])():
            self.register_index_provider(provider)
        for provider in getattr(domain_package, "get_symbol_lookup_providers", lambda: [])():
            self.register_symbol_lookup_provider(provider)
        for planner in getattr(domain_package, "get_action_planners", lambda: [])():
            self.register_action_planner(planner)
        for provider in getattr(domain_package, "get_repair_providers", lambda: [])():
            self.register_repair_provider(provider)
        for layer in getattr(domain_package, "get_reasoning_layers", lambda: [])():
            self.register_reasoning_layer(layer)

    def snapshot_context(self) -> tuple[dict[str, Any], InteractionSurface]:
        merged: dict[str, Any] = {}
        surface = InteractionSurface()
        for adapter in self.context_adapters:
            merged[adapter.name] = adapter.get_active_context()
            surface = adapter.get_interaction_surface()
        return merged, surface

    def list_tools(self) -> list[ToolSpec]:
        tools: list[ToolSpec] = []
        for bridge in self.capability_bridges:
            tools.extend(bridge.get_tools())
        return tools

    def build_system_instructions(self) -> tuple[str, ...]:
        instructions: list[str] = []
        for adapter in self.reasoning_adapters:
            base = adapter.get_system_instructions()
            if base:
                instructions.append(base)
            instructions.extend(item for item in adapter.get_prompt_overlays() if item)
        return tuple(instructions)

    def build_rule_sets(self, context: dict[str, Any]) -> tuple[RuleSet, ...]:
        rule_sets: list[RuleSet] = []
        for provider in self.rule_providers:
            rule_sets.extend(provider.get_rule_sets(context))
        return tuple(rule_sets)

    def knowledge_broker(self) -> KnowledgeBroker:
        return KnowledgeBroker(self.knowledge_sources)

    def code_understanding_broker(self) -> CodeUnderstandingBroker:
        return CodeUnderstandingBroker(self.code_understanding_providers)

    def index_registry(self) -> IndexRegistry:
        return IndexRegistry(self.index_providers)

    def symbol_lookup_broker(self) -> SymbolLookupBroker:
        return SymbolLookupBroker(self.symbol_lookup_providers)

    def repair_coordinator(self) -> RepairCoordinator:
        return RepairCoordinator(self.repair_providers)

    def run(self, request: str = "") -> KernelRunResult:
        context, surface = self.snapshot_context()
        tools = tuple(self.list_tools())
        instructions = self.build_system_instructions()
        rule_sets = self.build_rule_sets(context)
        model_route = self.model_router.choose_route(
            ModelRequest(task="kernel.run", prompt=request, context=context)
        )
        reasoning_result = self.reasoning_pipeline.run(request, context)
        validation = tuple(
            contract.validate_preconditions({"request": request, "context": context})
            for contract in self.validation_contracts
        )
        ok = all(report.ok for report in validation)
        return KernelRunResult(
            ok=ok,
            context=context,
            interaction_surface=surface,
            system_instructions=instructions,
            tools=tools,
            validation=validation,
            model_route=model_route,
            rule_sets=rule_sets,
            reasoning_result=reasoning_result,
            metadata={
                "request": request,
                "adapter_counts": {
                    "context": len(self.context_adapters),
                    "reasoning": len(self.reasoning_adapters),
                    "capability": len(self.capability_bridges),
                    "validation": len(self.validation_contracts),
                    "evidence": len(self.evidence_policies),
                    "escalation": len(self.escalation_policies),
                    "code_intelligence": len(self.code_intelligence_adapters),
                    "code_understanding": len(self.code_understanding_providers),
                    "rules": len(self.rule_providers),
                    "knowledge_sources": len(self.knowledge_sources),
                    "index_providers": len(self.index_providers),
                    "symbol_lookup_providers": len(self.symbol_lookup_providers),
                    "action_planners": len(self.action_planners),
                    "repair_providers": len(self.repair_providers),
                    "reasoning_layers": len(self.reasoning_pipeline.layers),
                },
            },
        )
