# Interaction Production Readiness Pass

Date: 2026-07-10

## Scope

This pass hardens the deterministic interaction layer already in place. It does
not add broad new DCC or graph capabilities.

## Rendering Verification

The production Qt application was not launched in this environment, so full
visual verification is not claimed.

Verified by code inspection and tests:

- clarification controls are native Qt widgets
- execution-plan and result-card summaries are deterministic text blocks inside
  the chat transcript
- recovery buttons are native Qt controls in the clarification strip
- provider refresh is asynchronous and polled through `QTimer`

Important distinction:

- backend execution plans and result cards are structured data
- chat rendering is currently rich/plain text, not a stateful in-place operation
  card widget
- clarification/recovery controls are stateful widgets, but they are not
  embedded into individual transcript messages

## Lifecycle Hardening

Added `services/interaction_lifecycle_service.py`.

The lifecycle manager owns:

- operation id
- continuation id
- provider request id
- provider generation
- operation revision
- cancellation state
- claimed action idempotency keys

Provider refresh now follows this rule:

1. refresh starts a provider request generation
2. the async provider job runs
3. completion checks operation id, continuation id, request id, slot, and
   generation
4. stale or superseded completions are ignored

This protects the common failure case:

- generation 1 starts
- generation 2 starts
- generation 2 completes
- generation 1 completes later
- generation 1 is ignored

## Cancellation And Replacement

When a new operation starts, the previous active operation is marked cancelled.

Cancelled operations cannot:

- accept provider results
- claim new actions
- update clarification schemas through the lifecycle path

Clarification replacement phrases such as `explain instead` still use the
existing continuation classifier and clear the pending operation.

## Duplicate Action Prevention

Added lifecycle idempotency claims for:

- clarification submit/cancel handling
- recovery actions
- workflow/pipeline run activation

The workflow run button also uses `_workflow_run_in_flight` to prevent repeated
terminal command staging while a run is considered active.

## Live Refresh And Reconnect

Implemented:

- provider refresh starts a generation-owned async job
- disconnected/failed provider controls can expose recovery buttons
- recovery actions route through `recovery_action_service`
- reconnect actions can trigger existing application reconnect methods
- refresh-after-reconnect reuses the same clarification control path

Still migration-required:

- host-specific reconnect should declare capability metadata
- refreshed values should be revalidated against already-bound values before
  automatic resume
- reconnect success metrics should be separated from operation success metrics

## Workflow And Pipeline Execution

Current state:

- workflow and graph run buttons both call `run_selected_workflow`
- duplicate activation is guarded
- saved workflow execution still has a direct bridge compatibility path

Migration still required:

- saved workflow run should become a typed graph execution request
- graph validation, missing-input clarification, node progress, partial failure,
  and recovery should all flow through the canonical action execution path
- bridge execution should move behind a registered graph/workflow adapter

This pass intentionally does not rewrite the runner because that is a larger
behavioral migration than lifecycle hardening.

## Menu And Toolbar Audit Summary

Direct UI-only actions allowed:

- tab switches
- focus changes
- panel resizing
- local filters
- visual graph editing gestures

Typed local commands acceptable:

- open file
- show log
- export file
- append generated code to a user-selected file after explicit dialog choice

Migration required:

- direct host selection/current-file menu actions
- saved workflow bridge execution
- Unreal utility dialog actions that mutate host/project state
- GitHub import actions that mutate project contents
- source-control mutation actions

## Tests Added

- `tests/test_interaction_lifecycle_service.py`
  - stale provider generation ignored
  - cancelled operation rejects late provider result
  - replacement operation invalidates old continuation
  - duplicate action claim suppressed

Updated static invariants:

- chat provider refresh must use lifecycle generation checks
- workflow run must include duplicate-action guard

## Verification

Commands run from `C:\depot\tools\mcp_servers\the_entire_world_ai_studio`:

```powershell
python -m py_compile .\services\interaction_lifecycle_service.py .\services\choice_provider_service.py .\services\interaction_quality_service.py .\services\recovery_action_service.py .\app\main_window_chat_runtime.py .\app\main_window_workflows.py .\tests\test_interaction_lifecycle_service.py .\tests\test_enterprise_interaction_invariants.py
```

Result: passed.

```powershell
python -m unittest tests.test_interaction_lifecycle_service tests.test_chat_continuation_service tests.test_choice_provider_service tests.test_recovery_action_service tests.test_prompt_dispatch_service tests.test_enterprise_interaction_invariants
```

Result: 37 tests passed.

```powershell
python -m unittest discover -s tests
```

Result: 111 tests passed.

## Remaining Intentional Exceptions

- result cards are not yet native in-place operation widgets
- saved workflow run remains a compatibility execution path
- direct DCC menu tools remain explicit tools, not chat routes
- terminal staging remains direct because it prepares commands for the terminal UI
- full Qt visual verification still needs a live app or offscreen preview harness

## Index Refresh Update

Normal project indexing is now stale-file-first:

- quick index runs `knowledge.build_knowledge_index_v2` in stale-only mode by default
- changed files are detected from indexed size/mtime/source metadata
- new supported files are added
- missing indexed files are removed from source-of-truth tables
- unchanged files are not reparsed
- FTS and dependency graph rebuilds are skipped when no indexed files changed
- `--full` is the explicit nuclear option for a full project scan

The UI button is labeled `Quick Index` to make the default behavior clear.

Next dependency-graph speedups, in order of safety:

1. Track changed Python modules from the stale-file plan.
2. Rebuild dependency rows only for changed source files and dependents.
3. Recompute unresolved import/module-resolution errors only for affected modules.
4. Batch graph updates in the background after search tables are already usable.
5. Keep a full graph rebuild as the repair path when graph state looks corrupted.
