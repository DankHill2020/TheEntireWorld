import json

import unreal


factory = unreal.AnimBlueprintFactory()
properties = {}
for name in ("target_skeleton", "parent_class", "preview_skeletal_mesh"):
    try:
        value = factory.get_editor_property(name)
        properties[name] = {"available": True, "value": str(value)}
    except Exception as exc:
        properties[name] = {"available": False, "error": str(exc)}
print(json.dumps(properties))
