# Direct DCC Bridge

The Studio now separates two kinds of requests:

## 1. Direct host actions

Fast deterministic calls that do not need the LLM.

```text
UI -> Maya commandPort -> result
UI -> Unreal HTTP bridge -> result
```

Use these for:

```text
current selection
current file
scene objects
asset lists
logs
simple tool calls
```

## 2. LLM reasoning

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

## Unreal

Unreal direct actions use Aaron's HTTP bridge:

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

## UI buttons

```text
Maya Selection
Maya File
Maya Objects
Unreal Skeletons
Unreal Meshes
Unreal Call
```

`Unreal Call` reads the input box as either a function path:

```text
unreal_tools.get_skeletons.get_all_assets_of_type
```

or JSON:

```json
{"function":"unreal_tools.get_skeletons.get_all_assets_of_type","args":["Skeleton","/Game/"],"kwargs":{}}
```