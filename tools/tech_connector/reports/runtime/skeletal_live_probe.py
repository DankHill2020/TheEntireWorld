import json

import unreal

from unreal_tools.skeletal import inspect_bones, inspect_sockets


mesh_path = (
    "/Game/Characters/Mannequins/Meshes/"
    "SKM_Manny_Simple.SKM_Manny_Simple"
)
print(
    json.dumps(
        {
            "bones": inspect_bones(mesh_path),
            "sockets": inspect_sockets(mesh_path),
        }
    )
)

factory_type = getattr(unreal, "AnimBlueprintFactory", None)
factory = factory_type() if factory_type else None
print(
    json.dumps(
        {
            "anim_blueprint_factory": bool(factory),
            "factory_properties": (
                sorted(
                    name
                    for name in dir(factory)
                    if any(
                        marker in name.lower()
                        for marker in ("skeleton", "parent", "blueprint")
                    )
                )
                if factory
                else []
            ),
        }
    )
)
