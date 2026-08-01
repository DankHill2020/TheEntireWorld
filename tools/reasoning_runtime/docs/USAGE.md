# Using `reasoning_runtime` In Your Own Project

`reasoning_runtime` is a standalone reasoning kernel. It does not import Tech
Connector, DCC applications, UI frameworks, or your application code. Your
project plugs in by implementing small adapter classes and installing them into
`ReasoningKernel`.

## Quick Start

```python
from reasoning_runtime import (
    CapabilityBridge,
    CapabilityResult,
    ContextAdapter,
    ReasoningAdapter,
    ReasoningKernel,
    ToolSpec,
    ValidationContract,
    ValidationReport,
)


class AppContext(ContextAdapter):
    name = "my_app_context"

    def get_active_context(self) -> dict:
        return {
            "active_project": "/repo/my-project",
            "active_file": "/repo/my-project/app.py",
            "user_mode": "review",
        }


class AppReasoning(ReasoningAdapter):
    name = "my_app_reasoning"

    def get_system_instructions(self) -> str:
        return "You reason about MyApp projects and preserve API compatibility."


class AppTools(CapabilityBridge):
    name = "my_app_tools"

    def get_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="my_app.search_docs",
                description="Search MyApp documentation.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                mutability="read_only",
                risk="low",
            )
        ]

    def execute_tool(self, tool_name: str, arguments: dict) -> CapabilityResult:
        if tool_name != "my_app.search_docs":
            return CapabilityResult(ok=False, error=f"Unknown tool: {tool_name}")
        return CapabilityResult(ok=True, output={"matches": []})


class AppValidation(ValidationContract):
    name = "my_app_validation"

    def validate_preconditions(self, request: dict) -> ValidationReport:
        return ValidationReport(
            ok=bool(request.get("request")),
            summary="Request text is present.",
        )


kernel = ReasoningKernel()
kernel.register_context_adapter(AppContext())
kernel.register_reasoning_adapter(AppReasoning())
kernel.register_capability_bridge(AppTools())
kernel.register_validation_contract(AppValidation())

result = kernel.run("Find the safest way to update the API client")
print(result.ok)
print(result.context)
print([tool.name for tool in result.tools])
```

A larger domain package usually exposes `get_*` factory methods and is installed
with `kernel.install(...)`:

```python
class MyDomainPackage:
    def get_context_adapters(self):
        return [AppContext()]

    def get_reasoning_adapters(self):
        return [AppReasoning()]

    def get_capability_bridges(self):
        return [AppTools()]

    def get_validation_contracts(self):
        return [AppValidation()]


kernel = ReasoningKernel()
kernel.install(MyDomainPackage())
result = kernel.run("Review payment retry behavior")
```

Domain packages may also expose `get_repair_providers()`. Each returned
`RepairProvider` proposes a bounded domain change; the runtime's
`RepairCoordinator` decides whether the validated transition made monotonic
progress. See [CONVERGENCE.md](CONVERGENCE.md).

## Core Runtime APIs

### `ReasoningKernel`

Import:

```python
from reasoning_runtime import ReasoningKernel
```

Common methods:

```python
kernel.register_context_adapter(adapter: ContextAdapter) -> None
kernel.register_reasoning_adapter(adapter: ReasoningAdapter) -> None
kernel.register_capability_bridge(bridge: CapabilityBridge) -> None
kernel.register_validation_contract(contract: ValidationContract) -> None
kernel.register_evidence_policy(policy: EvidencePolicy) -> None
kernel.register_escalation_policy(policy: EscalationPolicy) -> None
kernel.register_code_intelligence_adapter(adapter: CodeIntelligenceAdapter) -> None
kernel.register_model_router(router: ModelRouter) -> None
kernel.register_code_understanding_provider(provider: CodeUnderstandingProvider) -> None
kernel.register_rule_provider(provider: RuleProvider) -> None
kernel.register_knowledge_source(source: KnowledgeSource) -> None
kernel.register_index_provider(provider: IndexProvider) -> None
kernel.install(domain_package: Any) -> None
kernel.run(request: str = "") -> KernelRunResult
```

`KernelRunResult` includes:

```python
result.ok: bool
result.context: dict
result.interaction_surface: InteractionSurface
result.system_instructions: tuple[str, ...]
result.tools: tuple[ToolSpec, ...]
result.validation: tuple[ValidationReport, ...]
result.model_route: ModelRoute | None
result.rule_sets: tuple[RuleSet, ...]
result.reasoning_result: ReasoningLayerResult | None
result.metadata: dict
```

### `ContextAdapter`

Use this for context ingress.

```python
from reasoning_runtime import ContextAdapter, InteractionSurface


class MyContext(ContextAdapter):
    name = "my_context"

    def get_active_context(self) -> dict:
        return {"active_record_id": "ABC-123"}

    def get_interaction_surface(self) -> InteractionSurface:
        return InteractionSurface(
            kind="web_app",
            user_id="user-42",
            session_id="session-99",
            supports_clarification=True,
            supports_approval=True,
            metadata={"tenant": "acme"},
        )

    def get_permission_context(self) -> dict:
        return {"can_mutate": False, "approval_required": True}
```

### `ReasoningAdapter`

Use this for domain vocabulary, prompt overlays, gap policy, and code rules.

```python
from reasoning_runtime import ReasoningAdapter


class MedicalReasoning(ReasoningAdapter):
    name = "medical_reasoning"

    def get_system_instructions(self) -> str:
        return "Use clinical terminology carefully and distinguish evidence from advice."

    def get_domain_vocabulary(self) -> dict:
        return {
            "entities": ["patient", "medication", "lab_result"],
            "identifiers": ["ICD-10", "RxNorm", "LOINC"],
        }

    def get_gap_policies(self) -> list[dict]:
        return [
            {
                "gap": "drug_safety",
                "required_source": "official_drug_label",
                "min_confidence": 0.9,
            }
        ]

    def get_code_generation_rules(self) -> list[str]:
        return ["Never log PHI.", "Prefer explicit schema validation."]

    def get_patch_constraints(self) -> list[str]:
        return ["Do not change migration files without approval."]
```

### `CapabilityBridge`, `ToolSpec`, `CapabilityResult`

Use this for tools, APIs, host applications, databases, or shell-backed actions.

```python
from reasoning_runtime import CapabilityBridge, CapabilityResult, ToolSpec


class TicketBridge(CapabilityBridge):
    name = "ticket_bridge"

    def get_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="tickets.get",
                description="Fetch one ticket by id.",
                input_schema={
                    "type": "object",
                    "required": ["ticket_id"],
                    "properties": {"ticket_id": {"type": "string"}},
                },
                output_schema={"type": "object"},
                mutability="read_only",
                risk="low",
                permissions=("tickets:read",),
                execution_target="ticket_api",
                examples=({"ticket_id": "ENG-123"},),
            )
        ]

    def execute_tool(self, tool_name: str, arguments: dict) -> CapabilityResult:
        if tool_name == "tickets.get":
            return CapabilityResult(
                ok=True,
                output={"ticket_id": arguments["ticket_id"], "status": "open"},
                evidence=({"source": "ticket_api"},),
            )
        return CapabilityResult(ok=False, error=f"Unsupported tool: {tool_name}")
```

Recommended `ToolSpec.mutability` values:

- `read_only`
- `file_mutation`
- `external_mutation`
- `host_mutation`

Recommended `ToolSpec.risk` values:

- `low`
- `medium`
- `high`

### `ValidationContract`

Use this to define success and proof.

```python
from reasoning_runtime import ValidationContract, ValidationReport


class ApiValidation(ValidationContract):
    name = "api_validation"

    def validate_plan(self, plan: dict, context: dict) -> ValidationReport:
        has_tests = bool(plan.get("tests"))
        return ValidationReport(ok=has_tests, summary="Plan includes tests.")

    def validate_preconditions(self, request: dict) -> ValidationReport:
        return ValidationReport(ok=bool(request.get("request")))

    def validate_execution_result(self, result, context: dict) -> ValidationReport:
        return ValidationReport(
            ok=result.get("status") == "passed",
            checks=({"name": "status", "actual": result.get("status")},),
        )

    def validate_side_effects(self, result, context: dict) -> ValidationReport:
        return ValidationReport(ok=not result.get("unexpected_files"))

    def validate_completion(self, result, context: dict) -> ValidationReport:
        return ValidationReport(ok=bool(result.get("done")), evidence=(result,))
```

### Code Understanding And Generation

Use `CodeIntelligenceAdapter` for policy and `CodeUnderstandingProvider` for
repo/file/symbol comprehension.

```python
from reasoning_runtime import CodeGenerationPolicy, CodeIntelligenceAdapter
from reasoning_runtime import CodeContext, CodeUnderstandingProvider, CodeUnderstandingRequest


class AppCodePolicy(CodeIntelligenceAdapter):
    name = "app_code_policy"

    def get_generation_policy(self, context: dict) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(
            import_rules=("Use app.clients.http instead of raw requests.",),
            patch_constraints=("Keep public function signatures stable.",),
            validation_commands=("python -m pytest tests/api",),
            forbidden_patterns=("print(", "TODO: ignore error"),
        )

    def select_tests_for_change(self, changed_files: list[str], context: dict) -> list[str]:
        return ["tests/api/test_client.py"] if "app/client.py" in changed_files else []


class RepoUnderstanding(CodeUnderstandingProvider):
    name = "repo_understanding"

    def understand(self, request: CodeUnderstandingRequest) -> CodeContext:
        return CodeContext(
            summary=f"Query {request.query!r} over {len(request.project_roots)} root(s).",
            files=({"path": request.active_file, "role": "active_file"},),
            validation_candidates=("python -m pytest",),
        )
```

Use the broker:

```python
kernel.register_code_understanding_provider(RepoUnderstanding())
contexts = kernel.code_understanding_broker().understand(
    CodeUnderstandingRequest(
        query="where is retry behavior implemented?",
        project_roots=("/repo/my-project",),
        active_file="/repo/my-project/app/client.py",
        intent="locate",
    )
)
summary = kernel.code_understanding_broker().summarize(contexts)
```

### Knowledge Gaps And Indexing

Use `KnowledgeSource` for answering unknowns and `IndexProvider` for searchable
indexes.

```python
from reasoning_runtime import KnowledgeGap, KnowledgeSearchResult, KnowledgeSource
from reasoning_runtime import IndexBuildResult, IndexProvider, IndexQuery, IndexRecord, IndexSearchResult


class DocsKnowledge(KnowledgeSource):
    name = "docs_knowledge"

    def search(self, gap: KnowledgeGap, context: dict) -> list[KnowledgeSearchResult]:
        return [
            KnowledgeSearchResult(
                source="internal_docs",
                answer="Retry timeout defaults to 30 seconds.",
                confidence=0.82,
                locator="docs/retries.md",
            )
        ]


class DocsIndex(IndexProvider):
    name = "docs_index"

    def search(self, query: IndexQuery) -> list[IndexSearchResult]:
        record = IndexRecord(
            record_id="retries",
            title="Retries",
            text="Retry timeout defaults to 30 seconds.",
            source="docs",
            locator="docs/retries.md",
        )
        return [IndexSearchResult(record=record, score=0.91)]

    def build_or_update(self, roots: list[str], metadata: dict | None = None) -> IndexBuildResult:
        return IndexBuildResult(ok=True, indexed_count=42)
```

Use the brokers:

```python
kernel.register_knowledge_source(DocsKnowledge())
answers = kernel.knowledge_broker().search(
    KnowledgeGap(key="retry_timeout", question="What is the retry timeout?"),
    context={"project": "my-project"},
)

kernel.register_index_provider(DocsIndex())
matches = kernel.index_registry().search(IndexQuery(query="retry timeout", limit=5))
```

### Model Routing And Escalation

Model contracts live in `reasoning_runtime.models`.

```python
from reasoning_runtime.models import (
    EscalationDecision,
    EscalationPolicy,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    ModelRouter,
    ModelTier,
    ModelTierEscalationPolicy,
)


class LocalRouter(ModelRouter):
    name = "local_router"

    def choose_route(self, request: ModelRequest) -> ModelRoute:
        return ModelRoute(
            provider="ollama",
            model="qwen2.5-coder:7b",
            tier="standard",
            transport="local",
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        route = self.choose_route(request)
        return ModelResponse(ok=True, text="generated text", route=route)


kernel.register_model_router(LocalRouter())

policy = ModelTierEscalationPolicy(
    [
        ModelTier("small", "ollama", "qwen2.5-coder:3b"),
        ModelTier("standard", "ollama", "qwen2.5-coder:7b"),
        ModelTier("deep", "openai", "gpt-5.6-sol", transport="cloud"),
    ]
)
kernel.register_escalation_policy(policy)
```

Provider locking is useful when a request must not silently fall back to another
cloud/local provider:

```python
from reasoning_runtime.models import (
    ModelProviderRoute,
    locked_model_provider_route,
    model_provider_integrity,
)

route = ModelProviderRoute(
    provider="openai",
    model="gpt-5.6-sol",
    cloud_active=True,
    transport="cloud",
)

with locked_model_provider_route(route) as calls:
    calls.append({"provider": "openai", "model": "gpt-5.6-sol"})
    integrity = model_provider_integrity(route, calls)
    assert integrity["valid"]
```

### Request Preparation For App Pipelines

`RuntimeRequestPreparation` runs the kernel and attaches sanitized runtime
metadata to a `RequestContext`.

```python
from reasoning_runtime import ReasoningKernel, RuntimeRequestPreparation
from reasoning_runtime.engine.request_context import RequestContext

kernel = ReasoningKernel()
kernel.install(MyDomainPackage())

preparation = RuntimeRequestPreparation(kernel)
context, run_result = preparation.prepare(
    RequestContext(
        text="Review retry behavior",
        project_roots=("/repo/my-project",),
        current_file_path="/repo/my-project/app/client.py",
        extras={"api_key": "will_be_removed", "safe": "kept"},
    )
)

assert "api_key" not in context.extras
assert context.extras["reasoning_runtime"]["ok"] is True
```

## Complete Example

Run the bundled minimal domain package:

```powershell
python reasoning_runtime/examples/minimal_domain_package/minimal_domain.py
```

That example demonstrates context ingress, domain instructions, tool metadata,
validation, evidence policy, escalation policy, code-generation policy, and
installing a domain package into `ReasoningKernel`.
