"""Plug-and-play adapter contracts for domain packages."""

from reasoning_runtime.adapters.capability_bridge import (
    CapabilityBridge,
    CapabilityResult,
    ToolSpec,
)
from reasoning_runtime.adapters.code_intelligence_adapter import (
    CodeGenerationPolicy,
    CodeIntelligenceAdapter,
)
from reasoning_runtime.adapters.context_adapter import ContextAdapter, InteractionSurface
from reasoning_runtime.models import (
    EscalationDecision,
    EscalationPolicy,
    ModelTier,
    ModelTierEscalationPolicy,
)
from reasoning_runtime.adapters.evidence_policy import EvidencePolicy, EvidenceRecord
from reasoning_runtime.adapters.reasoning_adapter import ReasoningAdapter
from reasoning_runtime.adapters.repair_provider import (
    RepairContext,
    RepairProposal,
    RepairProvider,
)
from reasoning_runtime.adapters.validation_contract import (
    ValidationContract,
    ValidationReport,
)

__all__ = [
    "CapabilityBridge",
    "CapabilityResult",
    "CodeGenerationPolicy",
    "CodeIntelligenceAdapter",
    "ContextAdapter",
    "EscalationDecision",
    "EscalationPolicy",
    "ModelTier",
    "ModelTierEscalationPolicy",
    "EvidencePolicy",
    "EvidenceRecord",
    "InteractionSurface",
    "ReasoningAdapter",
    "RepairContext",
    "RepairProposal",
    "RepairProvider",
    "ToolSpec",
    "ValidationContract",
    "ValidationReport",
]
