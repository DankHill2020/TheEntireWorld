# Unreal Graph Prompt Smoke - 2026-07-13

## Goal

Drive a real Unreal graph edit through the Tech Connector prompt routing/dispatch path, using `BP_LesterPhoenix`, then log what matched the intended UX and what needed fixing.

Prompt used:

```text
In Unreal, add a temporary BeginPlay debug print node to BP_LesterPhoenix EventGraph that says AIStudio BeginPlay Probe, so I can test that prompt-driven graph edits are working.
```

## Initial Mismatches Found

- Prompt classification was correct: route `unreal_capability`, intent `unreal_semantic_graph_modification`.
- Dispatch converted `BP_LesterPhoenix` into a fake callable and rendered: `I'm ready to execute BP_LesterPhoenix`.
- The lower-level Unreal planner chose `project.debug` because high-risk graph detection missed `EventGraph` as a compact token and did not infer a concrete print-node graph patch.
- UE 5.8 does not expose the older `unreal.KismetEditorUtilities` APIs used by graph inspection/apply.
- UE 5.8 graph node access requires opening the Blueprint editor and using `BlueprintGraphEditor.get_graph_editor_by_name`.
- True visual node selection/zoom is not exposed by the available Unreal Python API. The safe behavior is to open the asset/graph, resolve the node, and report its position.

## Fixes Applied

- `services/dcc_execution_service.py`
  - Unreal graph prompts now build a graph rewrite preview/patch path instead of falling through to callable execution.
  - Approved graph requests run through `graph_patch_service.execute_patch`.
  - Graph prompts no longer treat Blueprint names as missing Python callables.

- `services/unreal/rewrite_plan_service.py`
  - Resolves named Blueprint assets such as `BP_LesterPhoenix` to package paths when Unreal is available.
  - Infers a `Development|PrintString` add-node operation for BeginPlay debug print requests.
  - Extracts the requested print message from prompt text.

- `bridges/unreal/unreal_bridge.py`
  - Replaced `KismetEditorUtilities` graph inspection/compile calls with UE 5.8-compatible APIs.
  - Added `focus_blueprint_graph_item`.
  - Added `Development|PrintString` node creation through `BlueprintGraphEditor.create_node_from_name`.
  - Sets `InString`, positions the node, connects `Event BeginPlay.then` to `PrintString.execute`, compiles, saves, and snapshots after apply.

- `services/clarification_service.py`
  - Confirmation text now names the graph patch target asset/graph instead of saying it will execute a callable.

## Live Result

Target:

```text
/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix
EventGraph
```

Created node:

```text
K2Node_CallFunction_6
Title: PrintString
Position: x=300, y=0
```

Verified pins:

```text
execute <- K2Node_Event_0.then
InString = AIStudio BeginPlay Probe
bPrintToScreen = true
bPrintToLog = true
Duration = 2.000000
```

Validation:

```text
Compile OK: true
Apply mode: applied
Errors: none
Backup asset: /Game/AIStudio/GraphPatchBackups/BP_LesterPhoenix_backup_ed8179fa
```

## Remaining Gaps

- The visible desktop UI still needs to render the full graph patch preview/details cleanly instead of only the compact confirmation text.
- The approval re-dispatch was simulated through `PromptDispatchService` with `approved=True`; the actual button flow should be checked in the running UI.
- `focus_blueprint_graph_item` can open the asset/graph and resolve the node/position, but UE Python does not currently expose true visual graph-node selection/zoom.
- The graph patch reporter should surface created node names, pin values, links, backup asset, and compile result in a more chat-like summary.
- Progress events are available in metadata, but the UI should stream graph edit lifecycle stages during approved execution.
