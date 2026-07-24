import json

import unreal


def names(value, markers):
    return sorted(
        name
        for name in dir(value)
        if any(marker in name.lower() for marker in markers)
    )


payload = {}
for class_name in (
    "RetargetSourceOrTarget",
    "AutoMapChainType",
    "IKRigDefinitionFactory",
    "IKRetargetFactory",
    "PoseSearchDatabaseFactory",
    "PoseSearchSchemaFactory",
    "NiagaraSystemFactoryNew",
    "PhysicsAssetFactory",
):
    value = getattr(unreal, class_name, None)
    payload[class_name] = {
        "available": value is not None,
        "names": names(
            value,
            (
                "source",
                "target",
                "exact",
                "fuzzy",
                "skeleton",
                "class",
                "asset",
            ),
        )
        if value is not None
        else [],
    }
print(json.dumps(payload))

physics_factory = unreal.PhysicsAssetFactory()
physics_properties = {}
for property_name in (
    "target_skeletal_mesh",
    "skeletal_mesh",
    "physics_asset_create_params",
):
    try:
        value = physics_factory.get_editor_property(property_name)
        physics_properties[property_name] = {
            "available": True,
            "value": str(value),
        }
    except Exception as exc:
        physics_properties[property_name] = {
            "available": False,
            "error": str(exc),
        }
print(json.dumps({"PhysicsAssetFactoryProperties": physics_properties}))
