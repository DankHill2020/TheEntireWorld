# DCC Smart Operations

Tech Connector should treat every connected DCC as a live editor with state, assets,
dependencies, and risk. It should not treat DCC work as generic chat.

The shared flow is:

```text
detect host -> snapshot context -> classify request -> plan typed operations
-> execute safe host endpoint -> validate -> report next fixes
```

The shared behavior starts in `bridges/host_bridge.py` on `DCCAdapter`.
Every DCC should inherit these baseline methods and only override them when it
can provide deeper host-specific facts:

```text
build_context_summary()
build_understanding_report(question)
build_prototype_plan(goal, template, context)
build_debug_report(goal, context)
```

This keeps understanding answers, prototype plans, and debug reports consistent
across Maya, Unreal, MotionBuilder, Blender, Substance Painter, Unity, and any
future bridge.

## Research Mode And Locked Knowledge

Research mode is layered. Local project facts should always outrank external
sources:

```text
project snapshot -> enabled host capabilities -> official docs
-> optional web techniques -> optional GitHub examples
-> architecture comparison -> implementation plan -> controlled execution
```

The settings dialog controls each layer. Live web/GitHub access is a global
gate; web techniques and GitHub examples remain separate research toggles so
the user can allow docs/pattern lookup without automatically ingesting external
code.

Tech Connector also keeps a compact local journal of controlled AI operations under
the app data folder, not in the repository. Future prompts receive only a small
relevant slice of this journal. When the system is behaving well, use:

```text
Tools -> Lock AI Knowledge Snapshot
```

Locked snapshots are frozen JSON knowledge files. They can grow over time, but
prompt context stays bounded: the app ranks recent and locked entries by host,
goal, target path, and keywords before injecting them into planning.

## Modes

### Inspect / Answer

Use this when the user asks what exists, what is selected, what a file contains,
or how a system works. Prefer direct host facts over model guesses. Query
selection, current file, scene objects, assets, and cached DCC context. Do not
mutate the project.

Examples:

```text
Maya what is selected?
Blender show scene objects.
MotionBuilder list takes.
Unreal what can I do inside a Blueprint?
```

### Prototype / Create / Implement

Use this when the user asks to make a feature, tool, setup, graph, rig, material
workflow, gameplay mechanic, or animation system.

Trigger words:

```text
prototype
create
implement
build
make
add
set up
setup
```

Examples:

```text
Unreal implement a rock climbing feature for my third person character.
Maya create a mocap retargeting cleanup workflow.
MotionBuilder prototype an animation take validation tool.
Blender build a scene cleanup tool for selected meshes.
Substance Painter create a smart texture export workflow.
Unity implement a lock-on targeting prototype.
```

Expected behavior:

```text
1. Snapshot host state first.
2. Inspect selected objects/assets and relevant dependencies.
3. Prefer existing assets, rigs, skeletons, materials, graphs, clips, takes, or prefabs.
4. Generate a concrete operation plan with named targets.
5. Execute only a known host endpoint.
6. Report created/modified assets, skipped steps, validation results, and rollback token.
7. Never claim graph edits or asset creation happened unless the host endpoint reports it.
```

### Debug / Diagnose

Use this when the user asks what is broken or what to fix.

Trigger words:

```text
debug
diagnose
what is broken
what's broken
broken
fix
validate
errors
warnings
not working
failing
full project
whole project
```

Expected behavior:

```text
1. Snapshot first.
2. Validate references/dependencies.
3. Compile/check host graphs when supported.
4. Report broken items grouped by severity.
5. Suggest a fix order.
6. Keep save disabled unless the user explicitly asks to save.
```

## Shared Payload Contract

Prototype payloads should include:

```json
{
  "host": "maya",
  "template": "retargeting_setup",
  "target_path": "/AIStudio/Prototypes/retargeting_setup",
  "parameters": {
    "feature_goal": "Maya create a mocap retargeting cleanup workflow",
    "mode": "prototype_or_create_or_implement",
    "context_excerpt": "...host snapshot...",
    "awareness": {
      "scan_scene_first": true,
      "inspect_selection": true,
      "inspect_assets_or_dependencies": true,
      "inspect_variables": true,
      "inspect_functions": true,
      "scan_connectable_properties": true,
      "prefer_existing_assets": true
    },
    "requested_outputs": [
      "operation_plan",
      "created_or_modified_assets",
      "changed_nodes_or_graphs",
      "new_slots_or_parameters",
      "validation_report",
      "rollback_token"
    ]
  }
}
```

Debug payloads should include:

```json
{
  "host": "motionbuilder",
  "paths": [],
  "save": false,
  "parameters": {
    "debug_goal": "MotionBuilder debug current character mapping",
    "scope": "scene_or_selection",
    "context_excerpt": "...host snapshot...",
    "requested_report": [
      "missing_references",
      "invalid_connections",
      "broken_nodes",
      "compile_or_script_errors",
      "missing_assets",
      "dependency_issues",
      "recommended_fix_order",
      "safe_fix_operations"
    ]
  }
}
```

## Per-Host Awareness

### Maya

Snapshot should include scene file, selection with keyable attrs, DAG hierarchy,
joints and root joint chains, skin clusters and influences, constraints,
namespaces, references, animation curves, playback range, and loaded plugins.

Natural-language Maya prompts can route to typed operations for viewport
navigation, panel opening, selection, attribute connections/disconnections,
constraints, material creation/assignment/color edits, skin binding, skin
influence edits, and direct API/tool calls. Built-in generated operations run
through the Maya commandPort and can use `maya.cmds`, `maya.api.OpenMaya`, and
legacy `maya.OpenMaya` when the user asks for explicit API access.

Examples:

```text
Maya frame hand_CTRL.
Maya open the node editor.
Maya connect ctrl.tx to joint.rx.
Maya parent constrain hand_CTRL to wrist_JNT with offset.
Maya create material heroMat red.
Maya bind skin mesh body_GEO with root_JNT spine_JNT.
Maya call maya.cmds.setAttr args ["ctrl.tx", 4].
Maya use maya.api.OpenMaya.MSelectionList.
```

Prototype examples include mocap retargeting cleanup, HIK characterization,
rig mapping creation, control picker generation, animation baking/export,
face rig helpers, and constraint/space switch setup.

Debug examples include missing references, unloaded namespaces, orphan
constraints, skin clusters with missing influences, disconnected controls,
animation curves outside playback range, missing HIK joints, and missing
plugin-dependent nodes.

### Unreal

Snapshot should include loaded level actors/components/tags, selected actors,
Blueprints, Blueprint variables/functions/components/interfaces, skeletal
assets, animation assets, input assets, DataAssets, GameModes/controllers,
plugins, dependencies, and referencers.

Prototype examples include rock climbing, motion matching locomotion, combat
combo abilities, time rewind, interaction systems, Blueprint template setups,
and AnimGraph or slot additions.

Debug examples include broken Blueprint compile, missing asset references,
invalid parent class, missing interface functions, animation skeleton mismatch,
input action not referenced, and level actors with missing components.

### Blender

Snapshot should include blend file, selected objects, scene objects,
collections, modifiers, materials, images/textures, armatures/bones, actions,
drivers, constraints, and library links.

Natural-language Blender prompts can route to generated bridge operations for
`bpy` scripting/API calls, viewport navigation, selection, primitive creation,
and material creation/assignment/color edits. These generated operations do not
require a checked-in `blender_tools` package; explicit `bpy.*` calls and scripts
run through the Blender socket bridge.

Examples:

```text
Blender run bpy.ops.mesh.primitive_cube_add kwargs {"size": 2}.
Blender create cube named TestCube.
Blender frame selection.
Blender create material heroMat red.
Blender assign material heroMat to Cube.
```

Prototype examples include scene cleanup tools, mesh export preparation,
material variants, rig control helpers, batch rename/collection organizers, and
Geometry Nodes setups from templates.

Debug examples include missing linked libraries, broken image paths, objects
with missing materials, invalid modifiers, armature/action mismatches, driver
errors, and non-applied transforms for export.

### Substance Painter

Snapshot should include project path, project status, texture sets, layers and
stacks when available, channels, mesh maps, export presets, and resource paths.

Prototype examples include texture export workflows, smart material application,
channel setup, mesh map validation, and multi-texture-set export presets.

Debug examples include missing mesh maps, missing texture sets, invalid export
preset, unresolved resources, channel mismatch, and unsaved project state.

### MotionBuilder

Snapshot should include file path, current take, takes and time spans,
selection, characters, control rigs, constraints, devices, and scene components.

Prototype examples include take cleanup workflows, character mapping
validation, mocap retargeting setup, animation export workflow, and control rig
bake helpers.

Debug examples include uncharacterized characters, inactive character inputs,
broken constraints, missing devices, empty takes, selected models without
expected transforms, and bad take frame ranges.

### Unity

Snapshot should include active scene path, selected GameObject, scene
GameObjects, components, prefabs, missing scripts, materials, animator
controllers, input actions, build settings scenes, and console errors when the
plugin exposes them.

Prototype examples include lock-on targeting, interaction components, combat
prototypes, movement abilities, prefab setup, and animator controller additions.

Debug examples include missing scripts, prefab overrides, null component
references, missing animator states/parameters, missing materials, compile
errors, and unassigned serialized fields.

## Endpoint Rule

The UI can route to these endpoints automatically, but the host package owns the
real implementation for package-backed prototype/debug work:

```text
maya_tools.ai_studio.prototype_from_template
maya_tools.ai_studio.debug_project
blender_tools.ai_studio.prototype_from_template
blender_tools.ai_studio.debug_project
substance_painter_tools.ai_studio.prototype_from_template
substance_painter_tools.ai_studio.debug_project
motionbuilder_tools.ai_studio.prototype_from_template
motionbuilder_tools.ai_studio.debug_project
unity AIStudioOperations.PrototypeFromTemplate(json)
unity AIStudioOperations.DebugProject(json)
unreal_tools.gameplay.prototype_from_template
unreal_tools.validate.references
```

For built-in generated smart operations, Tech Connector may use internal generated
operation functions such as `ai_studio.maya.generated.*` and
`ai_studio.blender.generated.*`. These are reviewed bridge scripts emitted by
the Studio, not external package functions, and should report the exact host API
call and result.

If an endpoint is missing, report the missing function exactly. Do not pretend
the operation succeeded.

## Report Quality Bar

Every smart operation should return:

```text
status
host
scope
context used
candidate assets/nodes
operation plan
actions actually performed
actions skipped and why
validation results
recommended next steps
rollback token if mutation occurred
```

Avoid vague responses like `done`, `endpoint reached`, or `operation completed`.
Unless a host endpoint actually modified assets or graphs, report the result as
`planned`, `diagnosed`, or `blocked`, not `created`.
