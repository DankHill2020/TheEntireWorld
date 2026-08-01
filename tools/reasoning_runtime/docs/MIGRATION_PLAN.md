# Reasoning Runtime Migration Plan

This plan describes the first safe slices for extracting a standalone reasoning
runtime from Tech Connector.

## Phase 1: Contracts And Domain Wrapper

Status: started.

Files added:

```text
reasoning_runtime/
reasoning_runtime/adapters/
reasoning_runtime/kernel.py
reasoning_runtime/docs/
tech_connector/adapters/
tech_connector/adapters/domain_package.py
reasoning_runtime/examples/minimal_domain_package/
```

No existing Tech Connector services are moved in this phase. The goal is to
establish the dependency direction:

```text
reasoning_runtime <- tech_connector domain package
```

The runtime must not import Tech Connector.

All connector files that know about Tech Connector live inside `tech_connector`.
This lets `reasoning_runtime` be downloaded, tested, and shipped independently.

## Phase 2: Action Graph Core

Move generic action graph code into `reasoning_runtime/action/`:

```text
tech_connector/services/action_contract_service.py
tech_connector/services/action_graph_service.py
generic parts of tech_connector/services/action_execution_engine.py
generic parts of tech_connector/services/action_planner_service.py
```

Keep Tech Connector-specific action handlers in Tech Connector. Existing files
should remain as compatibility shims until callers migrate.

## Phase 3: Engine Shell

Move generic request orchestration into `reasoning_runtime/engine/`:

```text
tech_connector/engine/progress_events.py
tech_connector/engine/request_context.py
generic parts of tech_connector/engine/request_engine.py
generic provider contracts from tech_connector/engine/providers.py
```

Prompt dispatch, UI behavior, and DCC routing stay in Tech Connector.

## Phase 4: Reasoning Services

Move domain-neutral reasoning services into `reasoning_runtime/reasoning/`:

```text
tech_connector/services/reasoning/answer_sufficiency_service.py
tech_connector/services/reasoning/clarification_service.py
tech_connector/services/reasoning/evidence_ranking_service.py
tech_connector/services/reasoning/problem_formulation_service.py
tech_connector/services/reasoning/rag_sufficiency_service.py
tech_connector/services/reasoning/semantic_execution_contract_service.py
tech_connector/services/reasoning/target_entity_service.py
tech_connector/services/reasoning/target_resolution_service.py
```

Split before moving:

```text
tech_connector/services/reasoning/goal_gap_planning_service.py
tech_connector/services/reasoning/engineering_reasoning_service.py
tech_connector/services/reasoning/request_understanding_fnn_service.py
tech_connector/services/reasoning/cognitive_routing_service.py
```

Those files contain Tech Connector/DCC concepts and need runtime/domain
separation first.

## Phase 5: Code Intelligence

Move generic code comprehension and generation services into
`reasoning_runtime/code_intelligence/`:

```text
tech_connector/services/code_intelligence_service.py
tech_connector/services/project_search_service.py
tech_connector/services/tool_discovery_service.py
tech_connector/services/tool_search_ranking_service.py
tech_connector/services/repo_map_service.py
tech_connector/services/validation_planner_service.py
```

DCC code-generation rules remain in `tech_connector/adapters/dcc_code_policy_adapter.py`.

## Phase 6: Model, Evidence, Recovery

Move generic model routing, evidence, and recovery abstractions after domain
imports are gone:

```text
tech_connector/services/llm_router_service.py
tech_connector/services/model_provider_service.py
tech_connector/services/ai_work_memory_service.py
tech_connector/services/symbol_evidence_service.py
tech_connector/services/recovery_action_service.py
```

Tech Connector-specific settings, account handling, licensing, and UI controls
stay in Tech Connector.

## Files That Stay In Tech Connector

```text
tech_connector/api.py
tech_connector/app/
tech_connector/ui/
tech_connector/bridges/
tech_connector/services/dcc/
tech_connector/services/unreal/
tech_connector/services/api_catalog_service.py
tech_connector/services/license_entitlement_service.py
tech_connector/models/constants.py
maya_tools/
unreal_tools/
blender_tools/
motionbuilder_tools/
tech_connector/docs/codex_prompts/*UNREAL*
```

## Validation Gates

Each phase should preserve:

```text
python -m unittest discover reasoning_runtime/tests
python -m unittest discover tech_connector/tests
python -c "import reasoning_runtime"
python -c "from tech_connector.adapters.domain_package import TechConnectorDomainPackage"
```

The most important architecture test is that `reasoning_runtime` imports without
Tech Connector or DCC packages.
