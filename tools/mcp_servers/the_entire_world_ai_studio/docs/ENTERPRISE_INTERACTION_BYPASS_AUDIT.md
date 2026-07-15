# Enterprise Interaction Bypass Audit

This audit distinguishes UI-local behavior from operations that must flow
through typed requests, dispatch handlers, adapters, clarification binding, and
structured results.

## Categories

### Acceptable Direct UI Actions

These may remain direct because they do not execute host/project mutations or
model reasoning:

- focusing widgets
- resizing panels
- toggling display-only options
- filtering visible lists
- opening local dialogs
- copying text
- expanding/collapsing trees

### Typed Local Application Commands

These do not need natural-language routing, but should use typed command or
service APIs where possible:

- open file
- reveal symbol
- open graph
- show logs
- navigate to a result
- stage a terminal command for manual execution

### Routed Or Dispatched Operations

These should not bypass the canonical services:

- natural-language chat requests
- DCC or Unreal execution
- graph/workflow execution
- source/project mutations
- code editing or generation
- Git/GitHub mutations
- model invocation
- project-wide analysis
- external tool execution

## Current Canonical Paths

- Natural-language chat routes through `PromptRouteService` and
  `PromptDispatchService`.
- Foreground DCC/Unreal chat execution routes through
  `DccExecutionRouteHandler` and `DccExecutionAdapter`.
- Clarification replies bind through `bind_clarification_response(...)` before
  any new prompt routing.
- Clarification choices are requested through `choice_provider_service`, not
  directly from widgets.
- Operation memory is passed through dispatch context and result metadata.
- DCC dispatch results carry execution plans, result cards, recovery options,
  and interaction metrics.
- Chat clarification refreshes now carry operation ids, continuation ids,
  provider request ids, and provider generations before async results are
  allowed to update UI state.
- Recovery buttons execute through `recovery_action_service`, with action
  idempotency claimed through `interaction_lifecycle_service`.

## Intentional Direct Or Compatibility Paths

These are currently tolerated, but should be reviewed before adding similar
paths:

- `app/main_window_ui.py` menu entries for direct Maya/Blender/MotionBuilder
  selection/current-file actions. These are explicit menu tools, not natural
  language chat. They should migrate to typed local commands or DCC adapters if
  they mutate host state.
- `ui/main_menu.py` duplicates some explicit host menu actions for menu
  construction. Same migration rule as above.
- `router/command_router.py` remains a compatibility bridge for existing Unreal
  command execution and preset calls. Chat should reach it through dispatch
  adapters, not by interpreting prompts downstream.
- `ui/unreal_editor_dialogs.py` owns the GitHub import dialog and some Unreal
  editor utility flows. Mutation-capable operations should migrate to typed
  actions as those services mature.
- Terminal staging actions remain direct because they stage commands in the
  terminal UI rather than silently executing model-selected operations.

## Migration Required

- Graph/workflow/pipeline run buttons should converge on one typed graph
  execution path that produces clarification, execution-plan, and result-card
  metadata.
- Mutation-capable menu/toolbar actions for DCC hosts should use typed command
  or dispatch paths so confirmation policy, operation memory, metrics, and
  structured results are preserved.
- GitHub import should eventually expose a non-UI service adapter for live
  search/selection so action graphs and recovery flows can resume without a
  synthetic chat prompt.
- Result-card actions should create typed command/continuation requests instead
  of injecting natural-language prompts.

## Invariants

1. Natural-language prompts are classified once.
2. Clarification responses bind before routing.
3. Executable routes use registered dispatch handlers.
4. Host execution uses registered adapters.
5. Clarification controls never query DCCs or indexes directly.
6. Choice providers return stable values separate from display labels.
7. Mutation should pass through confirmation policy.
8. Structured results should reach the UI without being flattened prematurely.
9. Operation memory must be scoped and invalidated before reuse.
10. Enterprise models are not used for deterministic presentation work.
11. UI-only behavior is not forced through prompt routing.

## Remaining Known Bypasses

- Explicit DCC menu actions in `app/main_window_ui.py` and `ui/main_menu.py`.
- Legacy compatibility methods in `router/command_router.py`.
- Dialog-owned GitHub search/import UI in `ui/unreal_editor_dialogs.py`.
- Workflow/pipeline execution paths that still generate files or scripts
  directly from graph UI state.

These are not all bugs. They are classified migration targets where execution,
mutation, or host state is involved.

## Rendering Architecture Finding

The current execution-plan and result-card rendering is structured in the
backend but text-rendered in the chat transcript. It is not yet a fully stateful
operation-card widget.

Current behavior:

- Execution plans and result cards are structured dictionaries in dispatch
  metadata.
- Chat appends deterministic `Execution Summary` text generated from that
  metadata.
- Clarification controls are native Qt widgets attached below the chat input
  area, not embedded into a specific transcript message.
- Provider refresh and recovery controls are stateful native Qt widgets, but
  the plan/result card itself is not yet interactively updateable in place.

Not yet supported by the transcript renderer:

- updating an existing result card in place
- preserving result-card expansion state
- attaching result-card actions to a transcript-local operation widget
- replacing loading state with completion state inside the same transcript card
- showing recovery actions without appending a recovery message

Smallest next UI abstraction:

- introduce an `OperationCardState` view model keyed by operation id
- keep the current text renderer as fallback
- render plan/result/recovery widgets from the same metadata
- reject updates when operation id, continuation id, or revision does not match
