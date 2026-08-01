# Reasoning Runtime Extension Guide

The `reasoning_runtime` package is the standalone reasoning kernel. It should be
usable without Tech Connector, Maya, Unreal, Blender, Qt, or any other domain
application installed.

Domain applications plug into the runtime by implementing a small set of
adapter contracts. Tech Connector is the canonical complex implementation, but
the runtime contracts are intentionally domain-neutral.

## Runtime Responsibilities

The runtime owns the reusable cognitive loop:

- collect active context
- understand the request
- detect missing knowledge or missing capabilities
- retrieve and rank evidence
- search indexed project/domain knowledge
- choose tools
- supervise execution
- validate results and side effects
- coordinate validation-to-repair convergence
- escalate models or strategies after failure
- record evidence and provenance
- support code comprehension, patch planning, generation, validation, and repair

The runtime must not import domain packages.

## Packaging Boundary

`reasoning_runtime` must be publishable and installable on its own. It cannot
depend on Tech Connector, Qt, DCC software, host bridge files, or Tech
Connector-specific settings.

Integration code belongs in the domain package that depends on the runtime:

```text
reasoning_runtime/
  domain-neutral contracts and kernel

tech_connector/
  adapters that import reasoning_runtime and wrap Tech Connector services
```

The dependency direction is one-way:

```text
tech_connector -> reasoning_runtime
reasoning_runtime -/-> tech_connector
```

When another product uses the runtime, it should create its own equivalent of
`tech_connector/adapters/` inside that product.

## Domain Responsibilities

A domain package owns the specifics:

- where user and environment context comes from
- domain vocabulary and prompt overlays
- knowledge sources and evidence rules
- tool and bridge implementations
- permission, mutability, and rollback rules
- code-generation rules for that domain
- validation contracts that prove completion
- bounded repair providers that know how to change domain candidates

## Extension Points

### 1. Context Adapter

Implement `ContextAdapter` when your app has active state the runtime should
see before planning.

Examples:

- Tech Connector: active project roots, DCC host state, open UI window
- Medical research: selected patient record, open paper, active cohort
- Legal documents: active matter, selected contract, jurisdiction
- Robotics: robot model, simulator state, safety zone

Required method:

```python
def get_active_context(self) -> dict[str, Any]:
    ...
```

Optional methods:

```python
def get_interaction_surface(self) -> InteractionSurface:
    ...

def get_permission_context(self) -> dict[str, Any]:
    ...
```

### 2. Reasoning Adapter

Implement `ReasoningAdapter` to guide understanding, planning, gap detection,
knowledge search, and code-generation behavior.

Important methods:

```python
def get_system_instructions(self) -> str:
    ...

def get_domain_vocabulary(self) -> dict[str, Any]:
    ...

def get_gap_policies(self) -> list[dict[str, Any]]:
    ...

def get_knowledge_sources(self) -> list[Any]:
    ...

def get_code_generation_rules(self) -> list[str]:
    ...

def get_patch_constraints(self) -> list[str]:
    ...
```

Keep domain assumptions here, not inside the runtime. For example, Unreal
Blueprint conventions belong in Tech Connector's reasoning adapter; PubMed
evidence rules belong in a medical research adapter.

### 3. Capability Bridge

Implement `CapabilityBridge` when the runtime can interact with tools, APIs,
host applications, databases, shell commands, or local services.

`get_tools()` returns structured `ToolSpec` objects. Do not return bare
functions unless they are wrapped in metadata. The runtime needs schemas,
mutability, permissions, risk, and target information to plan safely.

```python
ToolSpec(
    name="example.search",
    description="Search example records.",
    input_schema={"type": "object", "required": ["query"]},
    mutability="read_only",
    risk="low",
)
```

Tool execution returns `CapabilityResult`:

```python
CapabilityResult(ok=True, output={"items": []})
```

### 4. Validation Contract

Implement `ValidationContract` to define what "done" means.

Validation should be richer than one boolean:

- `validate_plan`
- `validate_preconditions`
- `validate_execution_result`
- `validate_side_effects`
- `validate_completion`

Tech Connector validation may require bridge readback, Unreal compile logs,
saved asset checks, or Maya scene state. Other domains can use tests, schema
checks, citations, database readback, simulations, or human approval.

### 5. Repair Provider

Implement `RepairProvider` when your domain can safely repair a candidate after
validation reports exact findings. The runtime owns provider selection and the
monotonic convergence decision; the provider owns the domain-specific edit.

Required methods:

```python
def supports(self, context: RepairContext) -> bool:
    ...

def repair(self, context: RepairContext) -> RepairProposal:
    ...
```

A provider returns a proposal. It does not declare itself successful and must
not permanently apply a candidate before the caller validates it. The runtime
accepts a transition only when the candidate changed, at least one prior finding
was resolved, and no protected regression was introduced.

See [CONVERGENCE.md](CONVERGENCE.md) for the lifecycle and ownership boundary.

### 6. Code Intelligence Adapter

Code comprehension and generation are foundational runtime features. Use
`CodeIntelligenceAdapter` to add domain-specific rules to generic code
understanding.

Examples:

- Tech Connector: host-specific modules may use their native imports, while
  cross-DCC execution routes through adapters or bridges. An explicit request
  constraint about transport or API ownership overrides the general default.
- Robotics: generated controller code must respect simulator safety constraints.
- Medical software: generated code must not log protected health information.

### 7. Evidence and Escalation Policies

Use `EvidencePolicy` and `EscalationPolicy` when a domain needs explicit rules
for trust, sufficiency, freshness, model tiering, or failure recovery.

Examples:

- Search more documentation when an API version is unknown.
- Escalate to a stronger model after validation failure.
- Refuse cloud model escalation for restricted projects.
- Require cited evidence before making a high-risk recommendation.

### 8. Index Provider

Implement `IndexProvider` when a domain has searchable local knowledge, code
indexes, document stores, symbol graphs, embedding indexes, or external search
APIs. This is separate from `KnowledgeSource`: an index provider is the low-level
retrieval surface, while a knowledge source can decide when and how to answer a
specific knowledge gap.

Important methods:

```python
def search(self, query: IndexQuery) -> list[IndexSearchResult]:
    ...

def build_or_update(self, roots: list[str], metadata: dict[str, Any] | None = None) -> IndexBuildResult:
    ...

def status(self) -> dict[str, Any]:
    ...
```

Examples:

- Tech Connector: local SQLite project knowledge index and symbol evidence
- Software IDE: repo index, dependency graph, language-server symbols
- Medical research: PubMed/cache index, papers, trial records, drug references
- Legal documents: matter documents, cited authorities, clause library

Runtime code should call `kernel.index_registry()` or depend on `IndexProvider`.
It should not import a concrete domain index implementation.

## Minimal Domain Package

See `reasoning_runtime/examples/minimal_domain_package/minimal_domain.py` for a complete runnable
domain package.

## Tech Connector Reference

Tech Connector implements the contracts in:

```text
tech_connector/adapters/
tech_connector/adapters/domain_package.py
```

Those adapters intentionally wrap the existing application instead of moving all
services at once. Generic convergence policy is already in `reasoning_runtime`;
concrete project-edit mutation and DCC behavior remain in Tech Connector behind
runtime contracts.

## Swappable Runtime Surfaces

The following pieces are intended to be replaced independently by another domain
package:

- context ingestion: `ContextAdapter`
- domain prompts and vocabulary: `ReasoningAdapter`
- tool/API/DCC interaction: `CapabilityBridge`
- completion proof: `ValidationContract`
- bounded domain repair: `RepairProvider`
- repair acceptance and monotonic progress: `ConvergencePolicy` and
  `RepairCoordinator`
- code comprehension/generation policy: `CodeIntelligenceAdapter`
- code context providers: `CodeUnderstandingProvider` through
  `CodeUnderstandingBroker`
- model selection/escalation: `ModelRouter` and `EscalationPolicy`
- provider lock/model telemetry: `ModelProviderRoute` and
  `locked_model_provider_route`
- local or cloud tier escalation: `ModelTierEscalationPolicy`
- rules and guardrails: `RuleProvider`, `EvidencePolicy`
- knowledge-gap answering: `KnowledgeSource`
- project/domain indexing: `IndexProvider`
- project analysis: `reasoning_runtime.project_analysis`
- prompt lifecycle state: `reasoning_runtime.prompt`
- prompt task/clause decomposition contracts:
  `reasoning_runtime.prompt.task_contracts`
- prompt resource orchestration contracts:
  `reasoning_runtime.prompt.resource_orchestration`
- planning/execution graph creation: `ActionPlanner`
- reasoning stages: `ReasoningLayer` in `LayeredReasoningPipeline`

## Compatibility Rule

Existing Tech Connector callers should continue importing from `tech_connector`.
The public `tech_connector.api` module remains the compatibility facade while
new runtime behavior is introduced underneath.

## Non-Negotiable Import Rule

This must always pass:

```python
import reasoning_runtime
```

in an environment where `tech_connector`, Qt, Maya, Unreal, Blender, and DCC
tool packages are unavailable.
