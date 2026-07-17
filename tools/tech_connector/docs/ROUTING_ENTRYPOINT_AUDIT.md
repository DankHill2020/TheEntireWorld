# Prompt Routing Entry Point Audit

This audit tracks natural-language project/DCC prompt entry points that must pass
through the canonical route decision before search, planning, model routing, DCC
execution, or graph composition.

## Inspected Entry Points

| File | Entry point | Current state | Risk | Required fix |
| --- | --- | --- | --- | --- |
| `app/main_window_chat_runtime.py` | `send_message` | Classifies once with `PromptRouteService`, stores `_last_prompt_route_decision`, sends engine routes and foreground DCC/Unreal routes through `PromptDispatchService`, and no longer contains the active Maya/Blender/Unreal shortcut execution body. | Low/medium. Explicit menu actions still call foreground methods directly, which is acceptable because they are not natural-language chat routing. | Continue promoting richer confirmed execution from adapters instead of reintroducing chat branches. |
| `app/main_window_chat_runtime.py` | `send_raw` | Raw model sends still bypass route classification by design. | Medium. Editor/target-discovery prompts that call `send_raw` can lose route metadata. | Pass route metadata into `send_raw` or require callers to attach the existing `prompt_route_decision`. |
| `app/main_window_workflows.py` | `build_pipeline_graph_from_prompt` | Now classifies the prompt before action-graph planning and refuses non-graph routes with route/mode/missing-slot feedback. | Low. It still calls the action planner directly after validation. | Acceptable for now because this is an explicit pipeline UI action; keep `_last_prompt_route_decision` as the bridge to the canonical dispatcher. |
| `router/command_router.py` | `execute_*_from_text`, `plan_unreal_request`, `unreal_detect_intent`, `maya_natural_language_to_python` | Existing direct host routers are still callable from explicit UI actions and host-specific service code. Chat no longer calls these directly. | Medium. Some host operations still need typed adapter implementations before mutation can proceed through dispatch. | Keep these as bridge implementation details behind adapters or explicit menu actions, not chat prompt routing. |
| `app/main_window_dcc.py` | `direct_*_from_text` | Explicit UI actions still use these methods. Chat route dispatch can call safe query adapters that delegate to existing foreground methods. | Medium. Mutating execute/prototype routes currently stop at structured confirmation/block states unless a safe adapter exists. | Promote confirmed execution methods into `DccExecutionAdapter` implementations incrementally. |
| `engine/providers.py` | `ActionGraphProvider`, `ProjectHealthProvider`, `TargetDiscoveryEditProvider`, `ProjectSearchProvider` | Engine providers still call their local `can_handle` predicates. | Low/medium. Duplicate route logic can drift from `prompt_route_service`. | Use `context.extras["prompt_route_decision"]` as the preferred can-handle source, falling back to local checks only for older callers. |

## Operational Routing Rules Added

- Every `PromptRouteDecision` now carries execution metadata:
  `execution_route`, `handler_id`, `operation_mode`, `target_type`,
  `execution_environment`, `mutation_scope`, `analysis_depth`,
  `context_resolvers`, `deterministic_steps`, `model_capability`,
  `risk_level`, `requires_fresh_index`, `requires_dcc_connection`,
  `requires_plan`, and `can_execute_directly`.
- Execution intent is separated from operation mode. For example:
  `Run create_rig` becomes `function_execution` with missing
  `execution_environment`, while `Run create_rig in Maya` becomes
  `dcc_execute`.
- Preview/plan-only language blocks execution and mutation:
  `Do not execute anything in Maya. Just show me how it would run.`
  resolves to `dcc_execute` with `operation_mode=preview`,
  `mutation_scope=read_only`, and no DCC connection requirement.
- Compound prompts are marked with `compound_kind` and ordered `operations`.
  Diagnose-then-fix prompts become `analysis_then_mutation` and require
  confirmation before mutation.
- Host hints now add scoped index filters. For example, `in unreal` sets
  `index_filters.scope=unreal_project`, limiting downstream project search to
  project/general Python plus Unreal-related indexed code instead of the entire
  index.

## Dispatcher Registry

`services.prompt_dispatch_service.PromptDispatchService` is the canonical
route-to-handler orchestrator. The registry maps `execution_route` values to
handlers:

- `engine.project_search` -> `ProjectSearchHandler`
- `engine.project_health` -> `ProjectHealthHandler`
- `engine.target_discovery` -> `TargetDiscoveryHandler`
- `engine.action_graph` -> `WorkflowHandler`
- `ui.github_import` -> `GitHubHandler` passthrough
- `llm.chat` -> `LocalLLMHandler` passthrough
- DCC/Unreal execution routes -> `DCCExecutionHandler`, backed by
  `services.dcc_execution_service`

Handlers declare required capabilities such as `active_project`,
`project_index`, `python_symbols`, `workflow_graph`, and `dcc_connection`.
The dispatcher checks these before invoking handlers and returns structured
clarification when required capabilities are missing.

Route metrics are appended as behavior-only JSONL events in
`.ai_studio/routing_metrics.jsonl`, including route, handler, confidence,
adapter, capability failure, missing argument state, preview/execution mode,
result type, timing, and LLM usage.

## DCC Execution Adapter Boundary

`services.dcc_execution_service` owns the typed foreground execution request:

- `DccExecutionRequest`
- `CapabilityFailure`
- `CapabilityCheckResult`
- `DccDispatchResult`
- `DccExecutionAdapter`

The handler converts route metadata into a typed request, resolves indexed
callable/signature metadata when available, blocks execution when required
arguments are missing, and keeps preview/query/execute as separate adapter
methods. A preview route cannot call the adapter's mutation method.

Current adapters:

- `maya`
- `blender`
- `motionbuilder`
- `substance_painter`
- `unreal`

Read-only query adapters can delegate to existing foreground methods such as
selection/file queries. Mutating execution is intentionally blocked or returned
as confirmation-required until the adapter has deterministic argument
resolution, capability validation, and confirmation/undo policy.

Compatibility preserved:

- Unreal read-only selection prompts such as `in unreal what is selected` route
  to `dcc_query` and the Unreal adapter delegates to the existing fast
  `direct_unreal_simple_question_from_text` path.

## Remaining Architecture Gap

The next smallest implementation step is to deepen the adapter implementations
for confirmed mutation:

- Maya callable execution with resolved arguments from selection/context.
- Unreal capability execution with reflection/capability metadata.
- Workflow/pipeline execution adapters.
- Confirmation acceptance/decline flow connected to the same dispatch envelope.
