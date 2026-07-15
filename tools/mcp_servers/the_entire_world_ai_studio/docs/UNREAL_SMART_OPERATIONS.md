# Unreal Smart Operations

Tech Connector should treat Unreal as a project-aware editor host, not as a place to
run arbitrary generated Python.

The intended flow is:

```text
scan -> classify -> plan -> execute approved operation -> validate -> report
```

## UI Entry Points

```text
Tools > Connected Applications > Unreal Engine > Open Unreal Engine
Tools > Connected Applications > Unreal Engine > Start / Stop Unreal Indexer
Tools > Connected Applications > Unreal Engine > Scan Project
Tools > Connected Applications > Unreal Engine > Index Unreal Docs
Tools > Connected Applications > Unreal Engine > Project Asset Scan
Tools > Connected Applications > Unreal Engine > Project Snapshot
Tools > Connected Applications > Unreal Engine > Debug Project / Find Broken
Tools > Connected Applications > Unreal Engine > Loaded Level Scan
Tools > Connected Applications > Unreal Engine > Inspect Asset / Blueprint
Tools > Connected Applications > Unreal Engine > Create Python Wrapper from C++
Tools > Connected Applications > Unreal Engine > Show Safe Operation Catalog
Tools > Connected Applications > Unreal Engine > Capability Validation
Tools > Connected Applications > Unreal Engine > Skeletons
Tools > Connected Applications > Unreal Engine > Meshes
Tools > Connected Applications > Unreal Engine > Call Function
Tools > Connected Applications > Unreal Engine > Undo Last Command
```

`Project Asset Scan` uses the current HTTP bridge and the existing
`unreal_tools.get_skeletons.get_all_assets_of_type` function to inventory core
asset classes under `/Game/`.

`Project Snapshot` runs a loaded-level scan and a project asset scan, then
returns both as one structured context bundle. Use this before asking the model
to create or modify gameplay, animation, Blueprint, or motion matching systems.

Tech Connector automatically runs `Project Snapshot` once when the Unreal HTTP bridge
is detected as connected. The cached snapshot is added to later Unreal prompts
so the model starts from real project facts instead of guessing asset paths.

`Loaded Level Scan` targets a stable Unreal-side endpoint:

```text
unreal_tools.level.scan_loaded_level
```

If the Unreal project does not expose that function yet, add it on the Unreal
Python side instead of letting the model improvise raw editor code.

## Operation Catalog

The typed operation catalog lives in:

```text
services/unreal_operation_service.py
```

It defines read-only and mutating operations with:

```text
operation key
display label
Unreal function path
required parameters
default optional parameters
whether the operation mutates the project
```

Representative operation keys:

```text
project.snapshot
level.scan_loaded
navigation.open_content_browser
navigation.open_asset
navigation.open_window
navigation.load_level
assets.dependencies
assets.inspect
blueprint.scan
blueprint.add_component
animation.find_compatible
animation.create_anim_bp
motion_matching.create_database
niagara.*
physics.*
blueprint.create_from_template
blueprint.compile
gameplay.prototype_from_template
validate.references
project.debug
rollback.latest
```

This list is intentionally representative. The authoritative current list is
the live catalog returned by `operation_catalog()` in
`services/unreal/unreal_operation_service.py` or by the menu action
`Show Safe Operation Catalog`. The catalog now also includes asset management,
level selection/deletion, Blueprint graph/function/variable operations,
animation state-machine operations, Sequencer, Niagara, PhysicsAsset,
retargeting, Control Rig, Motion Matching, and project reference/refactor
operations. Mutating entries are flagged with `mutates_project` and must pass
confirmation policy before execution.

Navigation requests such as opening a bare Blueprint name, Content Browser
folder, editor window, or level are parsed into the `navigation.*` operations.
These operations use the existing Unreal HTTP bridge and should inspect the
parsed bridge response payload, not only the outer transport envelope.

## Project Snapshot

Before asking the model to build animation trees, motion matching sets,
Blueprint setups, or gameplay prototypes, gather a snapshot:

```json
{
  "current_level": "/Game/Maps/TestArena",
  "actors": [],
  "skeletal_meshes": [],
  "skeletons": [],
  "animation_sequences": [],
  "animation_blueprints": [],
  "pose_search_databases": [],
  "blueprints": [],
  "input_actions": [],
  "input_mapping_contexts": [],
  "game_modes": [],
  "plugins_enabled": [],
  "warnings": []
}
```

The model should reason over this snapshot instead of guessing asset names or
paths.

## Safe Mutation Rule

Mutating operations should be explicit and typed. The model should produce an
intent like this:

```json
{
  "intent": "create_animation_prototype",
  "operation": "motion_matching.create_database",
  "requires_approval": true,
  "params": {
    "skeleton_path": "/Game/Characters/Hero/SK_Hero_Skeleton",
    "animation_paths": [
      "/Game/Characters/Hero/Animations/Run_Fwd",
      "/Game/Characters/Hero/Animations/Stop"
    ],
    "asset_path": "/Game/Characters/Hero/MotionMatching/MM_Hero_Locomotion"
  },
  "validation": ["validate.references", "blueprint.compile"]
}
```

The Unreal side owns the actual implementation. Tech Connector sends a known
operation payload through the HTTP bridge.

When a capability is not reachable from current Python/editor APIs, Tech Connector
can preview a reflected C++ wrapper plugin through:

```text
Tools > Connected Applications > Unreal Engine > Create Python Wrapper from C++
```

This path is opt-in through the `Allow Unreal C++ bridge` / `UE C++` setting.
It generates an `AIStudioBridge` wrapper plan first and only writes wrapper
files when the apply step is explicitly requested.

## Unreal-Side Endpoints To Add

The next Unreal Python package should implement these stable functions:

```text
unreal_tools.level.scan_loaded_level
unreal_tools.navigation.open_content_browser
unreal_tools.navigation.open_asset
unreal_tools.navigation.open_window
unreal_tools.navigation.load_level
unreal_tools.assets.get_dependencies
unreal_tools.assets.inspect_asset
unreal_tools.blueprint.scan_blueprint
unreal_tools.animation.find_compatible_animations
unreal_tools.animation.create_or_update_animation_blueprint
unreal_tools.motion_matching.create_pose_search_database
unreal_tools.blueprint.create_from_template
unreal_tools.blueprint.compile_blueprint
unreal_tools.gameplay.prototype_from_template
unreal_tools.validate.references
unreal_tools.rollback.latest
```

Prefer template-backed creation first. Add raw Blueprint graph editing later,
after scan, validation, and rollback are reliable.

## Example Endpoint: Loaded Level Scan

The Unreal-side function should return simple JSON-serializable data. Avoid
returning raw UObject instances.

```python
import unreal


def scan_loaded_level():
    editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    world = editor_subsystem.get_editor_world()

    actors = []
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        components = []
        for component in actor.get_components_by_class(unreal.ActorComponent):
            components.append({
                "name": component.get_name(),
                "class": component.get_class().get_name(),
            })
        actors.append({
            "name": actor.get_name(),
            "class": actor.get_class().get_name(),
            "path": actor.get_path_name(),
            "label": actor.get_actor_label(),
            "tags": [str(tag) for tag in actor.tags],
            "components": components,
        })

    selected = [
        actor.get_path_name()
        for actor in unreal.EditorLevelLibrary.get_selected_level_actors()
    ]

    return {
        "current_level": world.get_outer().get_path_name() if world else "",
        "actor_count": len(actors),
        "actors": actors,
        "selected_actors": selected,
        "dirty": bool(level_subsystem.get_levels(world)) if world else False,
    }
```

## Example Endpoint: Asset Dependencies

```python
import unreal


def get_dependencies(asset_path, recursive=True):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_searchable_names=False,
        include_soft_management_references=True,
        include_hard_management_references=True,
    )
    deps = registry.get_dependencies(asset_path, options)
    result = {
        "asset_path": asset_path,
        "dependencies": [str(dep) for dep in deps],
    }
    if recursive:
        seen = set(result["dependencies"])
        queue = list(seen)
        while queue:
            item = queue.pop(0)
            for dep in registry.get_dependencies(item, options):
                dep = str(dep)
                if dep not in seen:
                    seen.add(dep)
                    queue.append(dep)
        result["recursive_dependencies"] = sorted(seen)
    return result
```

## Example Endpoint: Inspect Asset

Use this for any specific asset path. It should return the generic facts first,
then specialized data when the asset class is known.

```python
import unreal


def inspect_asset(asset_path):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_data = registry.get_asset_by_object_path(asset_path)
    if not asset_data.is_valid():
        asset_data = registry.get_asset_by_package_name(asset_path)
    if not asset_data.is_valid():
        raise RuntimeError("Asset not found: {}".format(asset_path))

    tags = {}
    for key, value in asset_data.tags_and_values:
        tags[str(key)] = str(value)

    return {
        "asset_path": str(asset_data.object_path),
        "package_name": str(asset_data.package_name),
        "asset_name": str(asset_data.asset_name),
        "asset_class": str(asset_data.asset_class_path.asset_name),
        "package_path": str(asset_data.package_path),
        "tags": tags,
    }
```

## Example Endpoint: Scan Blueprint

The goal is to explain what a Blueprint does without opening graph editing yet.
Return functions, variables, components, interfaces, parent class, and high-level
graph feature names.

```python
import unreal


def scan_blueprint(asset_path, include_graphs=True, include_defaults=True):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise RuntimeError("Blueprint not found: {}".format(asset_path))

    generated_class = asset.generated_class() if hasattr(asset, "generated_class") else None
    parent_class = asset.parent_class.get_name() if getattr(asset, "parent_class", None) else ""

    variables = []
    for var in unreal.BlueprintEditorLibrary.get_blueprint_variables(asset):
        variables.append({
            "name": var.var_name,
            "type": str(var.var_type),
            "category": str(var.category),
        })

    functions = []
    for graph in unreal.BlueprintEditorLibrary.get_all_graphs(asset):
        graph_name = graph.get_name()
        nodes = unreal.BlueprintEditorLibrary.get_graph_nodes(graph) if include_graphs else []
        functions.append({
            "name": graph_name,
            "node_count": len(nodes),
            "features": sorted({node.get_class().get_name() for node in nodes})[:100],
        })

    components = []
    if generated_class:
        cdo = unreal.get_default_object(generated_class)
        for comp in cdo.get_components_by_class(unreal.ActorComponent):
            components.append({
                "name": comp.get_name(),
                "class": comp.get_class().get_name(),
            })

    return {
        "asset_path": asset_path,
        "parent_class": parent_class,
        "generated_class": generated_class.get_name() if generated_class else "",
        "variables": variables,
        "functions": functions,
        "components": components,
        "interfaces": [iface.get_name() for iface in getattr(asset, "implemented_interfaces", [])],
    }
```

Some Unreal Python builds expose different Blueprint editor helpers. Keep this
endpoint stable at the Tech Connector boundary even if the implementation needs
version-specific branches inside Unreal.

## Planning Prompt Shape

When a user asks for a prototype, feed the model:

```text
1. Project Snapshot output
2. User goal
3. Safe operation catalog
4. Relevant endpoint examples
```

Ask for a plan first:

```json
{
  "goal": "prototype third-person motion matching",
  "uses_existing_assets": true,
  "required_assets": ["skeleton", "compatible animations", "pose search schema"],
  "proposed_operations": [
    "animation.find_compatible",
    "motion_matching.create_database",
    "animation.create_anim_bp",
    "validate.references"
  ],
  "needs_confirmation": true
}
```

## Prototype / Create / Implement Mode

Natural Unreal requests that include words like `prototype`, `create`, or
`implement` are treated as editor-operation requests, not ordinary chat and not
asset inventory shortcuts.

Example:

```text
Unreal implement a rock climbing feature with animation slots
```

Tech Connector should:

```text
1. Ensure a Project Snapshot exists.
2. Use the snapshot as asset context.
3. Ask the Unreal operation layer to inspect candidate assets and Blueprints.
4. Scan Blueprint variables, functions, components, accessible functions, and
   connectable properties.
5. Find compatible animation assets when animation or anim graph work is needed.
6. Create required animation slots or prototype assets through controlled
   templates.
7. Validate references and compile touched Blueprints without saving unless the
   user explicitly requests save.
```

The UI routes these requests to:

```text
gameplay.prototype_from_template
validate.references
```

The operation payload includes:

```json
{
  "asset_awareness": {
    "scan_all_assets_first": true,
    "inspect_candidate_blueprints": true,
    "scan_blueprint_variables": true,
    "scan_blueprint_functions": true,
    "scan_accessible_functions": true,
    "scan_connectable_properties": true,
    "find_compatible_animations": true,
    "create_animation_slots": true,
    "prefer_existing_assets": true
  }
}
```

## Debug / Diagnose Mode

Natural Unreal requests that include `debug`, `diagnose`, `what is broken`,
`fix`, `errors`, `warnings`, or `not working` are routed to project diagnostics.

Example:

```text
Unreal debug full project and tell me what is broken
```

Tech Connector should:

```text
1. Gather a Project Snapshot.
2. Validate references.
3. Compile Blueprints when supported.
4. Report broken references, missing assets, Blueprint compiler errors/warnings,
   invalid parent classes, missing interfaces/functions, animation mismatches,
   and a recommended fix order.
5. Leave save disabled unless the user explicitly requests saving.
```

The UI routes these requests to:

```text
project.debug
```

Scoped examples:

```text
Unreal diagnose /Game/BP_Player
Unreal fix compile errors in /Game/BP_Player and /Game/UI/WBP_Menu
Unreal debug full project no compile
```
