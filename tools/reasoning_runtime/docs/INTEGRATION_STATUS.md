# Runtime Separation Integration Status

This document records the active ownership boundary between Tech Connector and
the standalone `reasoning_runtime` package.

## Completed In Current Slice

Runtime package boundary:

- `reasoning_runtime` imports without importing `tech_connector`.
- Runtime source tests reject domain imports such as `tech_connector`,
  `maya_tools`, `unreal_tools`, `blender_tools`, and `PySide`.
- Connector/adapters live inside `tech_connector`, not inside the runtime.

Runtime-owned primitives:

- `reasoning_runtime.action.action_contract_service`
- `reasoning_runtime.action.action_graph_service`
- `reasoning_runtime.engine.progress_events`
- `reasoning_runtime.engine.request_context`
- `reasoning_runtime.engine.runtime_request_engine`
- `reasoning_runtime.prompt.execution_state`
- `reasoning_runtime.prompt.execution_context`
- `reasoning_runtime.prompt.plan_verification`
- `reasoning_runtime.prompt.quality`
- `reasoning_runtime.prompt.resource_orchestration`
- `reasoning_runtime.prompt.task_contracts`
- `reasoning_runtime.prompt.text`
- `reasoning_runtime.project_analysis.package_layout`
- `reasoning_runtime.reasoning.answer_sufficiency_service`
- `reasoning_runtime.reasoning.target_entity_service`

UI/request path:

- `RequestEngine` installs `TechConnectorDomainPackage` into `ReasoningKernel`.
- `RequestEngine.process()` delegates reusable request preparation to
  `RuntimeRequestPreparation`.
- Prompt dispatch result metadata includes a `reasoning_runtime` snapshot.
- Runtime request metadata includes code-understanding summaries from registered
  `CodeUnderstandingProvider` implementations.
- UI pipeline action-graph materialization imports action graph helpers directly
  from `reasoning_runtime.action`.

Swappable component contracts:

- model routing
- provider lock and model-call telemetry
- local/cloud model tier escalation
- code understanding
- code-understanding aggregation
- knowledge-gap search
- indexing and retrieval providers
- rule providers
- action planning
- layered reasoning
- validation
- repair-provider coordination and convergence
- evidence
- escalation

Model escalation note:

- The runtime treats Ollama escalation as provider-neutral model-tier escalation.
- Tech Connector maps those tiers to Ollama profiles through
  `TechConnectorLocalModelEscalationPolicy`.
- Other products can map the same tiers to vLLM, LM Studio, OpenAI, Anthropic,
  internal gateways, or any other provider.

Prompt/project-analysis migration:

- Prompt stage quality report contracts now live in `reasoning_runtime.prompt`.
- Prompt evidence and understanding-validation state now live in
  `reasoning_runtime.prompt`.
- Prompt execution context now has a runtime base class. Tech Connector exports
  a subclass only for domain-specific execution-decision attachment.
- Prompt plan-verification extraction now lives in `reasoning_runtime.prompt`.
- Prompt task/clause/staged-prompt contracts now live in
  `reasoning_runtime.prompt`.
- Prompt resource-lane contracts now live in `reasoning_runtime.prompt`.
- Prompt text normalization now lives in `reasoning_runtime.prompt`.
- Package layout/import-cycle auditing now lives in
  `reasoning_runtime.project_analysis`.

## Active Domain Ownership

Tech Connector retains request dispatch, UI state, host/DCC routing, account and
license integration, project-specific evidence retrieval, concrete source-code
mutation, and domain validation. These are deliberate domain responsibilities,
not an extraction backlog.

## Validation And Repair Boundary

Generic convergence is now a runtime responsibility. `ConvergencePolicy`
compares validation findings before and after a candidate transition, and
`RepairCoordinator` selects installed `RepairProvider` implementations.

Tech Connector contributes `TechConnectorProjectEditRepairProvider` and keeps
the concrete project-edit responsibilities: locating safe symbol boundaries,
editing source, invoking project validators, and protecting domain-specific
failure classes. This is the active boundary; older documents that describe all
convergence as part of `code.project_edit_workflow` are historical.

## Indexing/Knowledge Boundary

Indexing belongs in the reusable runtime as a contract, because many domains
need the same reasoning behavior: detect a gap, search an index, rank evidence,
and decide whether the result is sufficient. Tech Connector now contributes its
local project index through `TechConnectorProjectIndexProvider`, while the
runtime only sees `IndexProvider`.

The current Tech Connector implementation still lives in
`tech_connector/services/project_search_service.py` and `tech_connector/knowledge`.
Those remain Tech Connector-specific implementations. Additional reusable index
lifecycle or ranking behavior may move into runtime services later, but callers
should already depend on the existing `IndexProvider` contract rather than those
concrete services.

## Verification Commands

```powershell
python -m unittest discover reasoning_runtime\tests
python -m unittest tech_connector.tests.test_reasoning_runtime_domain_package tech_connector.tests.test_request_engine_runtime_integration
python -m unittest tech_connector.tests.test_authenticated_model_providers
python -c "import reasoning_runtime, sys; print('tech_connector' in sys.modules)"
```
