# Direct DCC Bridge

The Studio separates two kinds of requests.

## 1. Direct Host Actions

Fast deterministic calls that do not need the LLM.

```text
UI -> Maya commandPort -> result
UI -> Unreal HTTP bridge -> result
UI -> Blender socket bridge -> result
UI -> Substance Painter socket bridge -> result
UI -> MotionBuilder socket bridge -> result
UI -> Unity socket bridge -> result
```

Use these for:

```text
current selection
current file
scene objects
asset lists
logs
simple tool calls
prototype/create/implement requests through known host package endpoints
debug/diagnose requests through known host package endpoints
```

For adding more apps, see `BRIDGE_ARCHITECTURE.md`.

For project-aware prototype/debug behavior across hosts, see
`DCC_SMART_OPERATIONS.md`.

## 2. LLM Reasoning

Requests that require planning, searching, generation, or explanation.

```text
UI -> MCPHost / LLM -> tools -> result
```

Use this for:

```text
find the right function
explain code
generate a tool
plan a rigging workflow
modify a system
```

## Maya

Maya direct actions use `maya_execute_and_capture` through the commandPort.
Natural chat prompts can now route built-in generated Maya operations through
that same bridge for navigation, selection, connections, constraints,
materials, skinning, `maya.cmds`, `maya.api.OpenMaya`, legacy `maya.OpenMaya`,
and importable `maya_tools.*` calls.

Examples:

```text
Maya frame selection.
Maya connect ctrl.tx to joint.rx.
Maya parent constrain hand_CTRL to wrist_JNT with offset.
Maya bind skin mesh body_GEO with root_JNT spine_JNT.
Maya call maya.cmds.setAttr args ["ctrl.tx", 4].
Maya use maya.api.OpenMaya.MSelectionList.
```

## Unreal

Unreal direct actions use the Tech Connector HTTP bridge:

```text
http://127.0.0.1:12347
```

Payload:

```json
{
  "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
  "args": ["Skeleton", "/Game/"],
  "kwargs": {}
}
```

`Unreal Call` reads the input box as either a function path:

```text
unreal_tools.get_skeletons.get_all_assets_of_type
```

or JSON:

```json
{"function":"unreal_tools.get_skeletons.get_all_assets_of_type","args":["Skeleton","/Game/"],"kwargs":{}}
```

The Unreal menu also exposes indexer/doc-index actions, project/debug scans,
capability validation, typed operation catalog display, and preview-first C++
wrapper generation for Python-inaccessible capabilities. Natural navigation
prompts can route to typed operations for opening Content Browser folders,
assets, editor windows, and levels.

## Blender

Blender direct actions use the Blender Tech Connector add-on, which starts a
localhost socket bridge inside Blender.
Natural chat prompts can route generated Blender operations through this bridge
for `bpy` scripting/API calls, navigation, selection, primitive creation, and
material edits even before a repository `blender_tools` package exists.

Examples:

```text
Blender run bpy.ops.mesh.primitive_cube_add kwargs {"size": 2}.
Blender create cube named TestCube.
Blender frame selection.
Blender create material heroMat red.
```

Setup:

```text
Start Tech Connector. It will install/update the Blender startup bridge when it can
find a Blender user folder.
Restart Blender if Tech Connector says the bridge was installed or updated.
Use Tools > Connected Applications > Blender in Tech Connector.
```

Manual options:

```text
Tools > Connected Applications > Blender > Install Startup Bridge
Tools > Connected Applications > Blender > Copy Script Editor Setup Snippet
Install_Blender_AI_Studio_Bridge.bat
```

The Script Editor snippet installs the startup bridge and starts the bridge in
the current Blender session. For a one-session manual test only, you can still
open Blender's Scripting workspace and run `blender_command_port_setup.py`.

Default port:

```text
127.0.0.1:7021
```

## MotionBuilder

MotionBuilder direct actions use the Tech Connector startup bridge and the
`MotionBuilderAdapter`.

Default port:

```text
127.0.0.1:7011
```

Direct actions currently expose:

```text
selection
current file
scene objects
takes
characters
context summary
raw Python execution
motionbuilder_tools / mobu_tools function calls
```

The context summary is the important awareness layer. It combines file state,
current take, component count, selected models, takes, characters, constraints,
and devices so planning can start from real MotionBuilder scene state.

## Unity

Unity direct actions use a socket bridge inside the Unity Editor.

Default port:

```text
127.0.0.1:7041
```

Direct actions currently expose:

```text
selection
current scene
scene GameObjects
debug project / find broken
prototype / create / implement
raw C# / editor execution through the Unity bridge
```

Unity is present in the direct UI and bridge code. It still needs plugin
registry parity before it is documented as a full plugin target alongside Maya,
Unreal, Blender, Substance Painter, and MotionBuilder.

## UI Buttons

```text
Maya Selection
Maya File
Maya Objects
Unreal Skeletons
Unreal Meshes
Unreal Call
Blender Selection
Blender File
Blender Objects
Blender Call / Execute
Substance Painter Project
Substance Painter Texture Sets
Substance Painter Call / Execute
MotionBuilder Selection
MotionBuilder File
MotionBuilder Scene Objects
MotionBuilder Takes
MotionBuilder Characters
MotionBuilder Context Summary
MotionBuilder Call / Execute
Unity Selection
Unity Current Scene
Unity Scene GameObjects
Unity Call / Execute
Per-host Debug Scene / Find Broken
Per-host Prototype / Create / Implement
```
