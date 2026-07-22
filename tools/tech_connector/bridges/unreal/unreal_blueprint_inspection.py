"""Read-only Blueprint inspection compatible with current Unreal Python APIs."""

from __future__ import annotations

import json
import re


def _function_summary(value):
    text = str(value)
    name = text
    marker = 'name: "'
    start = text.find(marker)
    if start >= 0:
        start += len(marker)
        end = text.find('"', start)
        name = text[start:end] if end >= 0 else text[start:]
    implemented = None
    marker = "is_implemented: "
    start = text.find(marker)
    if start >= 0:
        start += len(marker)
        end = text.find("}", start)
        raw = (text[start:end] if end >= 0 else text[start:]).strip()
        implemented = raw.lower().startswith("true")
    return {"name": name, "implemented": implemented}


def _pin_type_summary(pin_type):
    if pin_type is None:
        return ""
    try:
        text = pin_type.export_text()
    except Exception:
        return str(pin_type)
    category = ""
    object_type = ""
    for prefix, key in (("PinCategory=\"", "category"), ("PinSubCategoryObject=\"", "object")):
        start = text.find(prefix)
        if start < 0:
            continue
        start += len(prefix)
        end = text.find('"', start)
        value = text[start:end] if end >= 0 else text[start:]
        if key == "category":
            category = value
        else:
            object_type = value
    if object_type and "'" in object_type:
        parts = object_type.split("'")
        if len(parts) >= 2:
            object_type = parts[-2]
    return object_type or category or text


def _object_path(value):
    if value is None:
        return ""
    try:
        return str(value.get_path_name())
    except Exception:
        return str(value)


def scan_blueprint(asset_path, include_graphs=True, include_defaults=True):
    """Inspect a Blueprint without compiling, saving, or changing editor state."""
    import unreal

    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError("Blueprint asset not found: " + str(asset_path))

    result = {
        "asset_path": str(asset_path),
        "object_path": _object_path(asset),
        "class": asset.get_class().get_name(),
        "name": asset.get_name(),
        "parent_class": "",
        "generated_class": "",
        "variables": [],
        "functions": [],
        "components": [],
        "graphs": [],
        "defaults": {},
        "dependencies": [],
        "referencers": [],
        "compile_status": "not_compiled_during_read_only_scan",
        "section_status": {},
        "warnings": [],
        "errors": [],
        "sufficient": False,
    }

    try:
        parent = unreal.BlueprintEditorLibrary.get_blueprint_parent_class(asset)
        result["parent_class"] = parent.get_name() if parent else ""
        result["section_status"]["parent_class"] = True
    except Exception as exc:
        result["section_status"]["parent_class"] = False
        result["warnings"].append("parent_class unavailable: " + str(exc))

    generated = None
    try:
        generated = asset.generated_class()
        result["generated_class"] = _object_path(generated)
        result["section_status"]["generated_class"] = bool(generated)
    except Exception as exc:
        result["section_status"]["generated_class"] = False
        result["warnings"].append("generated_class unavailable: " + str(exc))

    try:
        variables = []
        inherited_count = 0
        for variable_name in unreal.BlueprintEditorLibrary.list_member_variable_names(asset):
            name = str(variable_name)
            if name.startswith("/Script/"):
                inherited_count += 1
                continue
            item = {"name": name, "type": "", "category": "", "replication": ""}
            try:
                item["type"] = _pin_type_summary(
                    unreal.BlueprintEditorLibrary.get_member_variable_type(asset, variable_name)
                )
            except Exception:
                pass
            try:
                item["category"] = str(
                    unreal.BlueprintEditorLibrary.get_blueprint_variable_category(asset, variable_name)
                )
            except Exception:
                pass
            try:
                item["replication"] = str(
                    unreal.BlueprintEditorLibrary.get_blueprint_variable_replication(asset, variable_name)
                )
            except Exception:
                pass
            variables.append(item)
        result["variables"] = variables
        result["inherited_variable_count"] = inherited_count
        result["section_status"]["variables"] = True
    except Exception as exc:
        result["section_status"]["variables"] = False
        result["warnings"].append("variables unavailable: " + str(exc))

    try:
        result["functions"] = [
            _function_summary(item)
            for item in unreal.BlueprintEditorLibrary.list_functions(asset)
        ]
        result["section_status"]["functions"] = True
    except Exception as exc:
        result["section_status"]["functions"] = False
        result["warnings"].append("functions unavailable: " + str(exc))

    if include_graphs:
        try:
            result["graphs"] = [
                {
                    "name": str(graph.get_name()),
                    "class": str(graph.get_class().get_name()) if graph.get_class() else "",
                }
                for graph in unreal.BlueprintEditorLibrary.list_graphs(asset)
            ]
            result["section_status"]["graphs"] = True
        except Exception as exc:
            result["section_status"]["graphs"] = False
            result["warnings"].append("graphs unavailable: " + str(exc))
    else:
        result["section_status"]["graphs"] = True

    default_object = None
    if generated:
        try:
            default_object = unreal.get_default_object(generated)
            result["defaults"]["object_path"] = _object_path(default_object)
            result["defaults"]["class"] = default_object.get_class().get_name()
        except Exception as exc:
            result["warnings"].append("default object unavailable: " + str(exc))

    if default_object and hasattr(default_object, "get_components_by_class"):
        try:
            components = default_object.get_components_by_class(unreal.ActorComponent)
            for component in components or []:
                item = {
                    "name": str(component.get_name()),
                    "class": str(component.get_class().get_name()),
                    "path": _object_path(component),
                }
                if item["class"] == "SkeletalMeshComponent":
                    for prop_name in ("skeletal_mesh_asset", "anim_class"):
                        try:
                            item[prop_name] = _object_path(component.get_editor_property(prop_name))
                        except Exception:
                            pass
                result["components"].append(item)
            result["section_status"]["components"] = True
        except Exception as exc:
            result["section_status"]["components"] = False
            result["warnings"].append("components unavailable: " + str(exc))
    else:
        result["section_status"]["components"] = True

    if include_defaults and default_object:
        try:
            movement = default_object.get_movement_component()
            if movement:
                movement_values = {}
                for prop_name in ("max_walk_speed", "jump_z_velocity", "air_control"):
                    try:
                        movement_values[prop_name] = movement.get_editor_property(prop_name)
                    except Exception:
                        pass
                result["defaults"]["movement"] = movement_values
        except Exception:
            pass

    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        package_path = result["object_path"].split(".", 1)[0]
        options = unreal.AssetRegistryDependencyOptions()
        result["dependencies"] = [
            str(item) for item in registry.get_dependencies(package_path, options)
        ]
        result["referencers"] = [
            str(item) for item in registry.get_referencers(package_path, options)
        ]
        result["section_status"]["references"] = True
    except Exception as exc:
        result["section_status"]["references"] = False
        result["warnings"].append("dependencies unavailable: " + str(exc))

    required_sections = ["parent_class", "generated_class", "variables", "functions"]
    if include_graphs:
        required_sections.append("graphs")
    missing_sections = [
        name for name in required_sections if not result["section_status"].get(name)
    ]
    result["missing_sections"] = missing_sections
    result["sufficient"] = not missing_sections
    if missing_sections:
        result["errors"].append(
            "Blueprint inspection is insufficient; unavailable sections: "
            + ", ".join(missing_sections)
        )
    return json.dumps(result, indent=2, default=str)


def _resolve_blueprint_path(unreal, target):
    target = str(target or "").strip()
    if target.startswith("/"):
        return target.split(".", 1)[0]
    if not target:
        selected = list(unreal.EditorUtilityLibrary.get_selected_assets() or [])
        blueprint_paths = []
        for asset in selected:
            try:
                class_name = str(asset.get_class().get_name())
                path = str(asset.get_path_name()).split(".", 1)[0]
            except Exception:
                continue
            if class_name in {"Blueprint", "AnimBlueprint"}:
                blueprint_paths.append(path)
        if len(blueprint_paths) == 1:
            return blueprint_paths[0]
        if len(blueprint_paths) > 1:
            raise ValueError("Expected one selected Blueprint, found %s" % len(blueprint_paths))
    matches = []
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for data in registry.get_assets_by_path("/Game", recursive=True):
        try:
            class_name = str(data.asset_class_path.asset_name)
        except Exception:
            class_name = str(getattr(data, "asset_class", ""))
        if class_name not in {"Blueprint", "AnimBlueprint"}:
            continue
        name = str(data.asset_name)
        if name.lower() == target.lower():
            matches.append(str(data.package_name))
    if len(matches) != 1:
        raise ValueError(
            "Expected one Blueprint named %s, found %s" % (target, len(matches))
        )
    return matches[0]


def scan_blueprint_by_query(target_asset, include_graphs=True, include_defaults=True):
    """Resolve a short or package Blueprint name and inspect it read-only."""
    import unreal

    return scan_blueprint(
        _resolve_blueprint_path(unreal, target_asset),
        include_graphs=include_graphs,
        include_defaults=include_defaults,
    )


def inspect_feature_context(target_asset, feature_query=""):
    """Return one compact live evidence package for Blueprint feature planning."""
    import unreal

    asset_path = _resolve_blueprint_path(unreal, target_asset)
    blueprint = json.loads(scan_blueprint(asset_path, True, True))
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    feature_terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", str(feature_query or ""))
        if term.lower() not in {
            "add", "create", "make", "build", "system", "feature", "unreal",
            "blueprint", "character", "reusable", "existing", "inspect", "plan",
        }
    }
    assets = {
        "input_actions": [],
        "input_mapping_contexts": [],
        "related_animations": [],
        "related_blueprints": [],
    }
    class_to_bucket = {
        "InputAction": "input_actions",
        "InputMappingContext": "input_mapping_contexts",
    }
    for data in registry.get_assets_by_path("/Game", recursive=True):
        try:
            class_name = str(data.asset_class_path.asset_name)
        except Exception:
            class_name = str(getattr(data, "asset_class", ""))
        name = str(data.asset_name)
        package = str(data.package_name)
        row = {"name": name, "path": package, "class": class_name}
        if class_name in class_to_bucket:
            assets[class_to_bucket[class_name]].append(row)
            continue
        searchable = (name + " " + package).lower()
        related = bool(feature_terms and any(term in searchable for term in feature_terms))
        if class_name in {"AnimSequence", "AnimMontage", "BlendSpace"} and related:
            assets["related_animations"].append(row)
        elif class_name in {"Blueprint", "AnimBlueprint"} and related:
            assets["related_blueprints"].append(row)

    for rows in assets.values():
        rows.sort(key=lambda row: row["path"].lower())

    animation_blueprints = []
    for component in blueprint.get("components") or []:
        anim_class = str(component.get("anim_class") or "")
        if not anim_class or "." not in anim_class:
            continue
        anim_path = anim_class.split(".", 1)[0]
        try:
            animation_blueprints.append(json.loads(scan_blueprint(anim_path, True, False)))
        except Exception as exc:
            blueprint.setdefault("warnings", []).append(
                "animation Blueprint inspection failed: " + str(exc)
            )

    result = {
        "target_asset": asset_path,
        "feature_query": str(feature_query or ""),
        "blueprint": blueprint,
        "animation_blueprints": animation_blueprints,
        "assets": assets,
        "sufficient": bool(blueprint.get("sufficient")),
        "errors": list(blueprint.get("errors") or []),
        "warnings": list(blueprint.get("warnings") or []),
    }
    return json.dumps(result, indent=2, default=str)
