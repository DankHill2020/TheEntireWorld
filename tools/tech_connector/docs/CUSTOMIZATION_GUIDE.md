# Customizing Tech Connector With Your Own Components

Tech Connector uses `reasoning_runtime` through a domain package:

```python
from tech_connector.adapters.domain_package import TechConnectorDomainPackage
```

The domain package lives at:

```text
tech_connector/adapters/domain_package.py
```

It installs Tech Connector adapters from:

```text
tech_connector/adapters/
```

This means you can customize Tech Connector by replacing or extending one
adapter at a time. The runtime stays standalone; all Tech Connector-specific
behavior stays inside Tech Connector.

## Current Domain Package Constructor

```python
TechConnectorDomainPackage(
    *,
    app_service: Any = None,
    window: Any = None,
    command_router: Any = None,
    project_root: str = "",
)
```

Arguments:

- `app_service`: optional application service object used by context/index adapters
- `window`: optional active UI window used for interaction context
- `command_router`: optional Tech Connector command router for tool execution
- `project_root`: optional active project root used by knowledge/index adapters

Usage:

```python
from reasoning_runtime import ReasoningKernel
from tech_connector.adapters.domain_package import TechConnectorDomainPackage

kernel = ReasoningKernel()
kernel.install(
    TechConnectorDomainPackage(
        app_service=my_app_service,
        window=my_main_window,
        command_router=my_command_router,
        project_root="C:/Projects/MyGame",
    )
)

result = kernel.run("Find the owner of the wall-run input binding")
```

## Extension Methods

`TechConnectorDomainPackage` exposes these factory methods:

```python
get_context_adapters() -> list[DccContextAdapter]
get_reasoning_adapters() -> list[DccReasoningAdapter]
get_capability_bridges() -> list[DccCapabilityBridge]
get_validation_contracts() -> list[DccValidationContract]
get_code_intelligence_adapters() -> list[DccCodePolicyAdapter]
get_model_router() -> TechConnectorModelRouter
get_escalation_policies() -> list[TechConnectorLocalModelEscalationPolicy]
get_code_understanding_providers() -> list[TechConnectorCodeUnderstandingProvider]
get_rule_providers() -> list[TechConnectorRuleProvider]
get_knowledge_sources() -> list[TechConnectorProjectKnowledgeSource]
get_index_providers() -> list[TechConnectorProjectIndexProvider]
get_repair_providers() -> list[TechConnectorProjectEditRepairProvider]
```

To customize behavior, subclass `TechConnectorDomainPackage` and override only
the method you need.

## Add A Custom Context Adapter

Use this when you want extra active context available to the runtime.

```python
from typing import Any

from reasoning_runtime import ContextAdapter, InteractionSurface
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioContextAdapter(ContextAdapter):
    name = "studio_context"

    def __init__(self, build_id: str, department: str) -> None:
        self.build_id = build_id
        self.department = department

    def get_active_context(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "department": self.department,
            "review_mode": "studio_gate",
        }

    def get_interaction_surface(self) -> InteractionSurface:
        return InteractionSurface(kind="tech_connector_ui")


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_context_adapters(self):
        return [
            *super().get_context_adapters(),
            StudioContextAdapter(build_id="CL-123456", department="animation"),
        ]
```

Install it:

```python
kernel.install(StudioTechConnectorPackage(project_root="C:/Projects/MyGame"))
```

## Add A Custom Reasoning Adapter

Use this for studio-specific language, rules, or prompt overlays.

```python
from tech_connector.adapters import DccReasoningAdapter
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioReasoningAdapter(DccReasoningAdapter):
    name = "studio_reasoning"

    def get_prompt_overlays(self) -> list[str]:
        return [
            *super().get_prompt_overlays(),
            "Prefer studio gameplay framework components over one-off Blueprint logic.",
            "Do not mark work complete until replay-map validation evidence is attached.",
        ]

    def get_domain_vocabulary(self) -> dict:
        vocabulary = dict(super().get_domain_vocabulary())
        vocabulary.setdefault("studio_terms", []).extend([
            "replay map",
            "combat sandbox",
            "animation gate",
        ])
        return vocabulary


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_reasoning_adapters(self):
        return [StudioReasoningAdapter()]
```

## Add A Custom Capability Bridge Tool

Use this when Tech Connector should expose a new tool/API/host action to the
runtime.

```python
from typing import Any

from reasoning_runtime import CapabilityResult, ToolSpec
from tech_connector.adapters import DccCapabilityBridge
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioCapabilityBridge(DccCapabilityBridge):
    def get_tools(self) -> list[ToolSpec]:
        return [
            *super().get_tools(),
            ToolSpec(
                name="studio.build_status",
                description="Read the current studio build status.",
                input_schema={
                    "type": "object",
                    "properties": {"stream": {"type": "string"}},
                },
                output_schema={"type": "object"},
                mutability="read_only",
                risk="low",
                execution_target="studio_ci",
            ),
        ]

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> CapabilityResult:
        if tool_name == "studio.build_status":
            return CapabilityResult(
                ok=True,
                output={
                    "stream": arguments.get("stream", "main"),
                    "status": "green",
                },
            )
        return super().execute_tool(tool_name, arguments)


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_capability_bridges(self):
        return [StudioCapabilityBridge(command_router=self.command_router)]
```

Tool metadata matters. Set these fields carefully:

- `name`: stable namespaced tool id, such as `studio.build_status`
- `input_schema`: JSON-schema-like argument description
- `mutability`: `read_only`, `file_mutation`, `external_mutation`, or `host_mutation`
- `risk`: `low`, `medium`, or `high`
- `permissions`: required permission labels
- `execution_target`: host or service that executes the action

## Customize Validation

Use this when your meaning of done is stricter than the default DCC checks.

```python
from typing import Any

from reasoning_runtime import ValidationReport
from tech_connector.adapters import DccValidationContract
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioValidation(DccValidationContract):
    name = "studio_validation"

    def validate_completion(self, result: Any, context: dict[str, Any]) -> ValidationReport:
        base = super().validate_completion(result, context)
        metadata = dict(getattr(result, "metadata", {}) or {})
        replay_passed = bool(metadata.get("replay_map_validation_passed"))
        return ValidationReport(
            ok=base.ok and replay_passed,
            summary="Studio replay-map validation is required.",
            checks=(
                {"name": "base_validation", "ok": base.ok},
                {"name": "replay_map_validation", "ok": replay_passed},
            ),
            evidence=base.evidence,
            errors=() if replay_passed else ("Missing replay-map validation evidence.",),
        )


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_validation_contracts(self):
        return [StudioValidation()]
```

## Customize Repair Execution

Use a repair provider when your domain has a bounded way to change a candidate
after validation identifies exact failures. Validation still decides what is
wrong, the provider proposes the domain edit, and the runtime accepts or rejects
the transition based on measured convergence.

```python
from reasoning_runtime import RepairContext, RepairProposal, RepairProvider
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioPublishRepair(RepairProvider):
    """Repair dictionary-backed studio publish candidates."""

    name = "studio_publish_repair"
    priority = 50

    def supports(self, context: RepairContext) -> bool:
        return isinstance(context.candidate, dict) and any(
            finding.metadata.get("repair_domain") == "studio_publish"
            for finding in context.findings
        )

    def repair(self, context: RepairContext) -> RepairProposal:
        candidate = dict(context.candidate)
        candidate["publish_status"] = "ready_for_validation"
        return RepairProposal(
            candidate=candidate,
            changed=candidate != context.candidate,
            metadata={"repair_domain": "studio_publish"},
        )


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_repair_providers(self):
        return [*super().get_repair_providers(), StudioPublishRepair()]
```

Do not use a repair provider to bypass validation or declare production
readiness. It should modify only the candidate boundary it owns and return
`changed=False` when it cannot make a real change. The coordinator rejects
unchanged proposals and protected regressions.

See [PROJECT_EDIT_CONVERGENCE.md](PROJECT_EDIT_CONVERGENCE.md) for Tech
Connector's concrete project-edit integration.

## Customize Code Generation Policy

Use this for import rules, patch constraints, validation commands, and forbidden
patterns.

```python
from reasoning_runtime import CodeGenerationPolicy
from tech_connector.adapters import DccCodePolicyAdapter
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioCodePolicy(DccCodePolicyAdapter):
    name = "studio_code_policy"

    def get_generation_policy(self, context: dict) -> CodeGenerationPolicy:
        base = super().get_generation_policy(context)
        return CodeGenerationPolicy(
            import_rules=(
                *base.import_rules,
                "Use studio.framework.asset_registry instead of scanning Content directly.",
            ),
            patch_constraints=(
                *base.patch_constraints,
                "Do not create new gameplay framework classes without architecture approval.",
            ),
            validation_commands=(
                *base.validation_commands,
                "python -m unittest discover tech_connector/examples/tests -p test_studio_*.py",
            ),
            forbidden_patterns=(
                *base.forbidden_patterns,
                "unreal.load_object(None, '/Game/Hardcoded')",
            ),
            metadata={**base.metadata, "studio_policy": True},
        )


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_code_intelligence_adapters(self):
        return [StudioCodePolicy()]
```

## Customize Model Routing

Use this when you want a studio-specific local/cloud route.

```python
from reasoning_runtime.models import ModelRequest, ModelRoute
from tech_connector.adapters import TechConnectorModelRouter
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioModelRouter(TechConnectorModelRouter):
    name = "studio_model_router"

    def choose_route(self, request: ModelRequest) -> ModelRoute:
        if "validation failure" in request.prompt.lower():
            return ModelRoute(
                provider="openai",
                model="gpt-5.6-sol",
                tier="deep",
                transport="cloud",
                fallback_allowed=False,
                metadata={"reason": "validation_repair"},
            )
        return super().choose_route(request)


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_model_router(self):
        return StudioModelRouter()
```

## Customize Model Escalation

Use this when failure should move through your own model ladder.

```python
from reasoning_runtime.models import ModelTier, ModelTierEscalationPolicy
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioEscalationPolicy(ModelTierEscalationPolicy):
    name = "studio_escalation"

    def __init__(self) -> None:
        super().__init__(
            [
                ModelTier("small", "ollama", "qwen2.5-coder:3b", "local"),
                ModelTier("standard", "ollama", "qwen2.5-coder:7b", "local"),
                ModelTier("deep", "openai", "gpt-5.6-sol", "cloud"),
            ]
        )


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_escalation_policies(self):
        return [StudioEscalationPolicy()]
```

## Customize Code Understanding

Use this when you want Tech Connector to understand your repository layout,
generated files, ownership, or validation tests.

```python
from reasoning_runtime import CodeContext, CodeUnderstandingRequest
from tech_connector.adapters import TechConnectorCodeUnderstandingProvider
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioCodeUnderstanding(TechConnectorCodeUnderstandingProvider):
    name = "studio_code_understanding"

    def understand(self, request: CodeUnderstandingRequest) -> CodeContext:
        base = super().understand(request)
        return CodeContext(
            summary=base.summary + " Studio ownership map is enabled.",
            files=base.files,
            symbols=base.symbols,
            dependencies=base.dependencies,
            validation_candidates=(
                *base.validation_candidates,
                "python -m unittest discover tech_connector/examples/tests -p test_studio_*.py",
            ),
            gaps=base.gaps,
            metadata={**base.metadata, "ownership_map": "studio"},
        )


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_code_understanding_providers(self):
        return [StudioCodeUnderstanding()]
```

## Customize Knowledge And Indexing

Use `TechConnectorProjectKnowledgeSource` for knowledge-gap answers and
`TechConnectorProjectIndexProvider` for searchable project records.

```python
from reasoning_runtime import KnowledgeGap, KnowledgeSearchResult
from tech_connector.adapters import (
    TechConnectorProjectIndexProvider,
    TechConnectorProjectKnowledgeSource,
)
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioKnowledgeSource(TechConnectorProjectKnowledgeSource):
    name = "studio_knowledge"

    def search(self, gap: KnowledgeGap, context: dict) -> list[KnowledgeSearchResult]:
        results = super().search(gap, context)
        if gap.kind == "studio_policy":
            results.append(
                KnowledgeSearchResult(
                    source="studio_policy",
                    answer="Replay validation is required before completion.",
                    confidence=0.95,
                    locator="studio/docs/validation.md",
                )
            )
        return sorted(results, key=lambda item: item.confidence, reverse=True)


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_knowledge_sources(self):
        roots = [self.project_root] if self.project_root else []
        return [StudioKnowledgeSource(project_roots=roots)]

    def get_index_providers(self):
        roots = [self.project_root] if self.project_root else []
        return [
            TechConnectorProjectIndexProvider(
                project_roots=roots,
                app_service=self.app_service,
            )
        ]
```

## Customize Rules

Use a rule provider when you want reusable guardrails to appear in runtime
metadata and reasoning.

```python
from reasoning_runtime import ReasoningRule, RuleProvider, RuleSet
from tech_connector.adapters.domain_package import TechConnectorDomainPackage


class StudioRuleProvider(RuleProvider):
    name = "studio_rules"

    def get_rule_sets(self, context: dict) -> list[RuleSet]:
        return [
            RuleSet(
                name="studio_completion",
                rules=(
                    ReasoningRule(
                        key="replay_validation_required",
                        text="Do not report gameplay work complete without replay-map evidence.",
                        severity="error",
                    ),
                ),
            )
        ]


class StudioTechConnectorPackage(TechConnectorDomainPackage):
    def get_rule_providers(self):
        return [*super().get_rule_providers(), StudioRuleProvider()]
```

## Wire Your Package Into The UI Path

`tech_connector.engine.request_engine.RequestEngine` currently installs
`TechConnectorDomainPackage` internally. For a persistent customization, replace
that construction point with your subclass:

```python
from tech_connector.adapters.domain_package import TechConnectorDomainPackage

self.runtime_kernel.install(
    TechConnectorDomainPackage(
        app_service=app_service,
        window=window,
        command_router=command_router,
        project_root=project_root,
    )
)
```

becomes:

```python
from my_studio.tech_connector_package import StudioTechConnectorPackage

self.runtime_kernel.install(
    StudioTechConnectorPackage(
        app_service=app_service,
        window=window,
        command_router=command_router,
        project_root=project_root,
    )
)
```

For local experiments, you can instantiate the runtime directly:

```python
from reasoning_runtime import ReasoningKernel
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.adapters.domain_package import TechConnectorDomainPackage

kernel = ReasoningKernel()
kernel.install(TechConnectorDomainPackage(project_root="C:/Projects/MyGame"))
print(kernel.run("Inspect animation blueprint dependencies").metadata)
```

## Validate Your Customization

Run the runtime boundary tests:

```powershell
python -m unittest discover reasoning_runtime\tests
```

Run the Tech Connector runtime smoke:

```powershell
python tech_connector\scripts\run_reasoning_runtime_smoke.py
```

Run a source compile check:

```powershell
python -m compileall -q reasoning_runtime tech_connector
```

The runtime must still pass this rule:

```text
reasoning_runtime must not import tech_connector
```

Custom Tech Connector code should live in Tech Connector or in your own package
that depends on `reasoning_runtime`; it should not be placed inside
`reasoning_runtime`.
