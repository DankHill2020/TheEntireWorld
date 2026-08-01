# Morning Deterministic Interaction Updates

Date: 2026-07-10

## Goal

Make project, DCC, Unreal, clarification, and pipeline-related chat operations more deterministic, testable, and recoverable. The LLM can still explain or interpret ambiguous requests, but routed operations should expose structured facts, planned steps, validation state, and recovery actions.

## Updates

### Authoritative routing and dispatch

- `PromptRouteService` classifies prompt intent before execution.
- `PromptDispatchService` is the canonical dispatcher for routed operations.
- DCC execution routes now return structured metadata:
  - execution plan
  - result card
  - recovery options
  - operation memory
  - selected adapter
  - dispatch result

### Deterministic DCC and Unreal execution flow

- DCC requests move through a deterministic pipeline:
  - route
  - resolve callable
  - inspect metadata
  - resolve context
  - validate arguments
  - execute or clarify
  - report
- Unreal short-route execution remains based on registered operation metadata instead of invented function names.
- Missing adapters, missing arguments, and confirmation-required operations now return structured clarification metadata.

### Clarification controls

- Clarification slots now carry UI metadata:
  - control type
  - choice provider id
  - provider filters
  - refresh policy
  - cache/context dependencies
  - stale-value execution policy
- Clarification binding uses stable values, not display labels.
- Pending clarification state can be resumed without rerouting through a heavier model.

### Choice providers

- Added generic `ChoiceProvider` infrastructure in `services/choice_provider_service.py`.
- Current provider families:
  - static values
  - operation memory
  - project files
  - project symbols/callables
  - Unreal skeletons
  - Unreal meshes
  - Unreal assets
  - registered Unreal operations
- Provider results include:
  - choices
  - stable typed values
  - stale state
  - latency
  - recovery options
  - refresh policy

### Async provider jobs

- Added `ChoiceProviderJobManager` so expensive provider lookups can run outside the UI thread.
- Job snapshots expose:
  - queued/running/completed/failed/cancelled state
  - provider id
  - slot name
  - result
  - error
- Chat clarification refresh now starts a provider job and polls it with `QTimer`, avoiding synchronous host/index calls from the button handler.

### Structured chat reporting

- Added readable renderers in `services/interaction_quality_service.py`:
  - `render_execution_plan_text`
  - `render_result_card_text`
  - `render_structured_interaction_summary`
- Chat output now appends an `Execution Summary` when dispatcher metadata includes a plan or result card.
- The summary is generated from structured metadata, not by asking the LLM to explain what happened.

### Recovery actions

- Added `services/recovery_action_service.py`.
- Recovery options are now executable action requests instead of plain labels.
- Supported recovery actions include:
  - reconnect Unreal/current host
  - retry
  - refresh choices
  - choose host
  - enter manually
  - clarify
  - show diagnostics
  - rebuild index
- Clarification controls display recovery buttons when a provider reports disconnected, failed, empty, or stale state with no choices.

### Enterprise interaction bypass audit

- Added `docs/ENTERPRISE_INTERACTION_BYPASS_AUDIT.md`.
- The audit separates:
  - acceptable direct UI actions
  - typed local application commands
  - routed/dispatched operations
- Static tests now guard against reintroducing direct host execution from chat clarification UI paths.

## Files Changed In This Pass

- `app/main_window_chat_runtime.py`
  - Appends structured execution summaries for answer/clarify/error results.
  - Runs clarification choice refresh through async provider jobs.
  - Displays executable recovery buttons for failed/disconnected provider states.

- `services/choice_provider_service.py`
  - Adds `ChoiceProviderJobSnapshot`.
  - Adds `ChoiceProviderJobManager`.
  - Adds global `CHOICE_PROVIDER_JOBS`.

- `services/interaction_quality_service.py`
  - Adds deterministic text rendering for execution plans and result cards.

- `services/recovery_action_service.py`
  - Adds executable recovery action handling.

- `tests/test_choice_provider_service.py`
  - Adds async provider job coverage.

- `tests/test_interaction_quality_service.py`
  - Adds structured rendering coverage.

- `tests/test_recovery_action_service.py`
  - Adds executable recovery coverage.

## Verification

Commands run from `C:\depot\tools\tech_connector`:

```powershell
python -m py_compile .\services\choice_provider_service.py .\services\interaction_quality_service.py .\services\recovery_action_service.py .\app\main_window_chat_runtime.py .\examples\tests\test_choice_provider_service.py .\examples\tests\test_interaction_quality_service.py .\examples\tests\test_recovery_action_service.py
```

Result: passed.

```powershell
python -m unittest discover -s .\examples\tests -p "test_choice_provider_service.py"
python -m unittest discover -s .\examples\tests -p "test_interaction_quality_service.py"
python -m unittest discover -s .\examples\tests -p "test_recovery_action_service.py"
python -m unittest discover -s .\examples\tests -p "test_prompt_dispatch_service.py"
```

Result: 26 tests passed.

```powershell
python -m unittest discover -s .\examples\tests
```

Result: 105 tests passed.

## Remaining Gaps

- Native result-card widgets are still text-rendered in chat. The service layer is ready for richer Qt cards, but the current pass keeps rendering stable and testable.
- Recovery actions are generic and window-method based. Host-specific recovery should eventually declare capability metadata the same way execution handlers do.
- Provider jobs support cancellation state, but running host calls cannot always be interrupted if the host bridge blocks internally.
- Project/code edit approval flows still need to fully converge on the same Action Graph/Execution Plan contract.
- GitHub ingestion should become an explicit action in the same planner/executor path before it is wired into pipeline creation.
- Metrics exist around routing/dispatch, but provider latency, clarification recovery usage, and recovery success rates should be promoted into the same routing-quality dashboard.
