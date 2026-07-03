# Universal Direct Calls

The goal is:

```text
Any Maya Python function -> direct Maya commandPort
Any Unreal Python function -> direct Unreal HTTP bridge
```

## Maya

Maya direct call supports:

### Raw Maya Python

Paste into the input box:

```python
import maya.cmds as cmds
print(cmds.ls(sl=True))
```

Then press:

```text
Maya Call
```

### Function payload

Paste JSON:

```json
{
  "function": "maya_tools.rigging.create_rig.create_brow_main_setup",
  "args": [],
  "kwargs": {}
}
```

Then press:

```text
Maya Call
```

The UI sends this to Maya through commandPort and executes the function inside Maya.

## Unreal

Unreal direct call supports:

### Function path

Paste:

```text
unreal_tools.get_skeletons.get_all_assets_of_type
```

Then press:

```text
Unreal Call
```

### Function payload

Paste JSON:

```json
{
  "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
  "args": ["Skeleton", "/Game/"],
  "kwargs": {}
}
```

Then press:

```text
Unreal Call
```

## Important

This is the fast deterministic path:

```text
UI -> Host bridge -> function -> result
```

The LLM path should be reserved for reasoning, planning, searching, and code generation.