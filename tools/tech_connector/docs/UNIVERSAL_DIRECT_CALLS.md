# Universal Direct Calls

The goal is:

```text
Any Maya Python function -> direct Maya commandPort
Any Unreal Python function -> direct Unreal HTTP bridge
Any Blender Python function -> direct Blender socket bridge
Any Substance Painter Python function -> direct Substance Painter socket bridge
Any MotionBuilder Python function -> direct MotionBuilder socket bridge
Any Unity editor command -> direct Unity socket bridge
```

## Maya

Maya direct call supports:

### Raw Maya Python

Paste into the input box:

```python
import maya.cmds as cmds
print(cmds.ls(sl=True))
```

Maya prompt-routed calls can also target `maya.cmds`,
`maya.api.OpenMaya`, legacy `maya.OpenMaya`, and importable `maya_tools.*`
functions:

```text
Maya call maya.cmds.setAttr args ["ctrl.tx", 4].
Maya use maya.api.OpenMaya.MSelectionList.
```

Then use:

```text
Tools > Connected Applications > Maya > Call / Execute
```

### Function Payload

Paste JSON:

```json
{
  "function": "maya_tools.rigging.create_rig.create_brow_main_setup",
  "args": [],
  "kwargs": {}
}
```

Then use:

```text
Tools > Connected Applications > Maya > Call / Execute
```

## Unreal

Unreal direct call supports:

### Function Path

Paste:

```text
unreal_tools.get_skeletons.get_all_assets_of_type
```

Then use:

```text
Tools > Connected Applications > Unreal Engine > Call Function
```

### Function Payload

Paste JSON:

```json
{
  "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
  "args": ["Skeleton", "/Game/"],
  "kwargs": {}
}
```

Then use:

```text
Tools > Connected Applications > Unreal Engine > Call Function
```

## Blender

Blender direct call supports:

### Raw Blender Python

Paste into the input box:

```python
import bpy
print([obj.name for obj in bpy.context.selected_objects])
```

Blender prompt-routed calls support explicit `bpy.*` functions and scripts
through the socket bridge, even while there is no checked-in `blender_tools`
folder:

```text
Blender run bpy.ops.mesh.primitive_cube_add kwargs {"size": 2}.
```

Then use:

```text
Tools > Connected Applications > Blender > Call / Execute
```

### Function Payload

Paste JSON:

```json
{
  "function": "blender_tools.mesh.create_test_cube",
  "args": [],
  "kwargs": {}
}
```

Use `blender_tools.*` function payloads only after that package exists in the
project or is installed in the running Blender environment.

Then use:

```text
Tools > Connected Applications > Blender > Call / Execute
```

## Substance Painter

Substance Painter direct call supports raw Python or a JSON function payload.

Use:

```text
Tools > Connected Applications > Substance Painter > Call / Execute
```

## MotionBuilder

MotionBuilder direct call supports raw Python or a JSON function payload whose
function starts with `motionbuilder_tools.*` or `mobu_tools.*`.

Use:

```text
Tools > Connected Applications > MotionBuilder > Call / Execute
```

## Unity

Unity direct call supports editor bridge execution when the Unity socket bridge
is running.

Use:

```text
Tools > Connected Applications > Unity > Call / Execute
```

## Important

This is the fast deterministic path:

```text
UI -> Host bridge -> function -> result
```

The LLM path should be reserved for reasoning, planning, searching, and code generation.
