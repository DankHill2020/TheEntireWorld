# Unreal Python Quick Reference

For Unreal actions, prefer UnrealGenAI MCP tools first.
Use `unrealgenai__execute_python_script` when needed.

## Selected actors
```python
import unreal
actors = unreal.EditorLevelLibrary.get_selected_level_actors()
print([a.get_actor_label() for a in actors])
```

## All level actors
```python
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
print([(a.get_actor_label(), a.get_class().get_name()) for a in actors])
```

## Spawn cube
```python
import unreal
asset = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 100))
actor.set_actor_label("AI_Test_Cube")
actor.static_mesh_component.set_static_mesh(asset)
print(actor.get_actor_label())
```

## Add tools depot to sys.path
```python
import sys
path = r"C:/depot/tools"
if path not in sys.path:
    sys.path.append(path)
print("Added tools path")
```

## Safety
Ask before deleting, saving, overwriting, submitting, mass renaming, or editing project settings.
