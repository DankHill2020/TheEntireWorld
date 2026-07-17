# UI Features Guide

This guide describes the main Tech Connector surfaces from a user point of view.

## Chat

Use Chat for natural requests, direct DCC calls, and routed model sessions.

Primary controls:

```text
Auto cloud -> local / Always local
Model
Use fallback models
Settings
Start MCPHost
Stop
Cancel Query
Prime
Tools
Web/GitHub
UE C++
Send
Paste Image
Attach Images
```

The model router sends DCC-heavy requests such as Maya, Unreal, Blender,
Substance Painter, Unity, and MotionBuilder work to the DCC/code model family.
Complex Unreal/engine tasks can escalate to the configured deep local model.
`Use fallback models` switches routed sessions to the fallback role map and
restarts warm routed sessions so the next prompt uses the selected family.

## Tools Menu

The Tools menu exposes deterministic workflows that do not require the model to
guess.

Important sections:

```text
Tech Connector Tools
Model & Safety
Knowledge
Community Tools
VCS Accounts / Login
Lock AI Knowledge Snapshot
Show AI Knowledge Summary
Auto Checkout on Change
Model Providers
App Updates
Connected Applications
Settings
```

Use direct host actions for facts and simple editor commands. Use the model for
planning, code generation, explanation, and multi-step reasoning.

## Unreal

Use Unreal direct actions when the Unreal HTTP bridge is running.

```text
Tools > Connected Applications > Unreal Engine > Open Unreal Engine
Tools > Connected Applications > Unreal Engine > Start / Stop Unreal Indexer
Tools > Connected Applications > Unreal Engine > Scan Project
Tools > Connected Applications > Unreal Engine > Index Unreal Docs
Tools > Connected Applications > Unreal Engine > Project Snapshot
Tools > Connected Applications > Unreal Engine > Project Asset Scan
Tools > Connected Applications > Unreal Engine > Debug Project / Find Broken
Tools > Connected Applications > Unreal Engine > Loaded Level Scan
Tools > Connected Applications > Unreal Engine > Inspect Asset / Blueprint
Tools > Connected Applications > Unreal Engine > Create Python Wrapper from C++
Tools > Connected Applications > Unreal Engine > Skeletons
Tools > Connected Applications > Unreal Engine > Meshes
Tools > Connected Applications > Unreal Engine > Show Safe Operation Catalog
Tools > Connected Applications > Unreal Engine > Capability Validation
Tools > Connected Applications > Unreal Engine > Call Function
Tools > Connected Applications > Unreal Engine > Undo Last Command
```

`Project Snapshot` gathers loaded-level data plus asset inventory. Tech Connector
runs this automatically once when the Unreal HTTP bridge connects, then includes
the cached snapshot in later Unreal prompts. This keeps the model grounded in
real project assets and loaded-level state.

`Project Asset Scan` gathers asset inventory only. Use it when you want a fresh
asset-class inventory without the loaded-level endpoint.

`Inspect Asset / Blueprint` reads the current input box as an asset path or JSON
payload and asks Unreal for asset-level facts such as class, tags, dependencies,
Blueprint variables, functions, components, and graph features.

`Create Python Wrapper from C++` previews a reflected `AIStudioBridge` Unreal
plugin wrapper for capabilities that Python/editor APIs cannot reach directly.
The `UE C++` setting must be enabled before planning can recommend this route,
and wrapper generation is preview-first.

Natural prompts that ask to open Unreal assets, Content Browser folders, editor
windows, or levels are routed through typed navigation operations such as
`navigation.open_asset`, `navigation.open_content_browser`,
`navigation.open_window`, and `navigation.load_level`.

`Call Function` accepts either a function path:

```text
unreal_tools.get_skeletons.get_all_assets_of_type
```

or a JSON payload:

```json
{
  "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
  "args": ["Skeleton", "/Game/"],
  "kwargs": {}
}
```

## Editor

Use Editor for code inspection and controlled edits.

Primary controls:

```text
Go to File Location
Save File
Find
Go
Duplicate Line
Comment
Trim Spaces
Ask About File
Ask Selection
Ask AI
Plan Edit
Apply Fix
Full Screen
```

`Apply Fix` reviews proposed code changes before writing them and creates a
backup for safer edits.

## Search / Symbols

Use Search / Symbols to find project functions, classes, callers, and
implementations. This is the best place to discover reusable local functions
before asking the model to invent new code.

## Workflows

The Workflows tab saves repeatable tool chains.

Saved workflow controls:

```text
Create New Workflow
Refresh List
Save Parameters
Run in DCC
Run Test
View Test Log
Delete
Edit Visually
Export .py
Append to File
```

Visual builder controls:

```text
Workflow Name
Host
Workflow Goal / Description
Function Search
Add Step
Visual steps
Python Code
Save & Compile Workflow
```

Each visual step has:

```text
Inputs
Outputs
Connections
Up
Down
Remove
```

Inputs can use literal values or `Link` to a previous step output. Outputs are
editable and show a `Connect As` key such as:

```text
$step1.body_joint_map
```

Output names must be valid Python identifiers because they are used in generated
workflow code.

Use `Up` and `Down` to reorder workflow steps. Tech Connector preserves still-valid
connections by step object and refreshes connection keys after the move.

Editor analysis and diff approval surfaces include `Add to Workflow`. The menu
contains `New Workflow` plus saved workflows, so useful file analysis or a
proposed patch can be captured as workflow reference context.

## Web / GitHub Import

Use Web / GitHub Import to search for external code, ingest a repository,
refresh discovered functions, suggest links, compose a workflow, and save it
into the local workflow registry.

This is useful when you want the model to use a better local training/context
set instead of relying only on general knowledge.

GitHub ingestion is UI-mediated. Chat routes that detect repository-ingestion
intent open the import dialog so the user can review the repo/source before
download, indexing, or workflow composition.

Accepted GitHub inputs include:

```text
owner/repo
github.com/owner/repo
https://github.com/owner/repo
git@github.com:owner/repo.git
https://github.com/owner/repo/tree/branch-name
https://github.com/owner/repo/releases/tag/tag-name
https://github.com/owner/repo/commit/sha
```

## Model Providers

Configure model source and provider setup from:

```text
Settings
Tools > Model Providers
```

Modes:

```text
Auto cloud -> local
Always local
```

Provider API keys are expected through environment variables or explicit
credential flows, not hidden page scraping.

## Source & Runtime Settings

The Settings dialog also owns runtime/source controls that should not crowd the
main chat row:

```text
MCPHost config
Allow live Web/GitHub sources
Allow GitHub tools in workflow composition
Research Mode: project snapshot, Unreal capabilities, official docs, web
techniques, GitHub examples, architecture comparison, plan before edit, auto
implement
Use previous AI work
Include locked AI knowledge
Allow Unreal C++ bridge
Simple chat responses
Show reasoning summary
External tools folder
```

The main `Web/GitHub` checkbox is a quick toggle for live sources. The workflow
composer's GitHub-tool permission is configured in Settings so it is clear that
it affects composition/ingestion behavior, not every chat prompt.

## App Updates

Use:

```text
Tools > App Updates > Check Git Status
Tools > App Updates > Update from Latest
Tools > App Updates > Update from Git Ref
```

Updates refuse to run when local changes are present.

## DCC Bridge Setup

Use direct bridge actions when the host app is open and its bridge is running.

Supported direct-host areas:

```text
Maya
Unreal
Blender
Substance Painter
Unity
MotionBuilder
```

Maya, Unreal, Blender, Substance Painter, Unity, and MotionBuilder have direct
UI entries. The plugin registry currently tracks Maya, Unreal, Blender,
Substance Painter, and MotionBuilder; Unity is present as a direct bridge/menu
integration and still needs registry parity before it matches the older hosts
as a plugin target.

For bridge architecture and contributor details, see:

```text
docs/DIRECT_DCC_BRIDGE.md
docs/DCC_SMART_OPERATIONS.md
docs/BRIDGE_ARCHITECTURE.md
docs/UNREAL_SMART_OPERATIONS.md
```
