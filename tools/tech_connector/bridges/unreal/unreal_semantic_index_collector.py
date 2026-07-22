"""Live Unreal collector for the desktop semantic project index."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from unreal_tools.assets import load_asset


def _safe(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return ""


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()


def _asset_class_name(data: Any) -> str:
    try:
        return _safe(data.asset_class_path.asset_name)
    except Exception:
        return _safe(getattr(data, "asset_class", ""))


def _asset_tags(data: Any) -> dict[str, str]:
    try:
        return {str(key): _safe(value) for key, value in dict(data.tags_and_values).items()}
    except Exception:
        return {}


def _pin_direction(unreal, pin: Any) -> str:
    for name in ("get_pin_direction", "get_direction"):
        try:
            value = _safe(getattr(unreal.BlueprintGraphPinLibrary, name)(pin)).lower()
            if "output" in value:
                return "output"
            if "input" in value:
                return "input"
        except Exception:
            continue
    return "unknown"


def _reflection_name(value: Any) -> str:
    for attribute in ("function_name", "variable_name", "name"):
        try:
            candidate = getattr(value, attribute)
            candidate = candidate() if callable(candidate) else candidate
            if candidate:
                return _safe(candidate)
        except Exception:
            continue
    try:
        return _safe(value.get_name())
    except Exception:
        return _safe(value)


def _node_title(unreal, node: Any) -> str:
    try:
        return _safe(unreal.BlueprintEditorLibrary.get_node_title(node))
    except Exception:
        return _safe(node.get_name())


def _blueprint_details(unreal, asset_path: str, asset: Any) -> dict[str, Any]:
    details: dict[str, Any] = {
        "asset_path": asset_path,
        "kind": "blueprint",
        "parent_class": "",
        "generated_class": "",
        "variables": [],
        "functions": [],
        "components": [],
        "graphs": [],
        "errors": [],
    }
    try:
        details["parent_class"] = _safe(unreal.BlueprintEditorLibrary.get_blueprint_parent_class(asset))
    except Exception:
        pass
    try:
        generated_class = asset.generated_class
        generated_class = generated_class() if callable(generated_class) else generated_class
        details["generated_class"] = _safe(generated_class.get_path_name() if generated_class else "")
    except Exception:
        pass
    try:
        details["variables"] = [
            {"name": _safe(name)}
            for name in unreal.BlueprintEditorLibrary.list_member_variable_names(asset) or []
        ]
    except Exception as exc:
        details["errors"].append("variables: " + _safe(exc))
    try:
        details["functions"] = [
            {"name": _reflection_name(function)}
            for function in unreal.BlueprintEditorLibrary.list_functions(asset) or []
        ]
    except Exception as exc:
        details["errors"].append("functions: " + _safe(exc))
    try:
        subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        library = unreal.SubobjectDataBlueprintFunctionLibrary
        for handle in subsystem.k2_gather_subobject_data_for_blueprint(asset) or []:
            data = library.get_data(handle)
            obj = None
            try:
                obj = library.get_object_for_blueprint(data, asset)
            except Exception:
                pass
            details["components"].append(
                {
                    "name": _safe(library.get_display_name(data)),
                    "variable": _safe(library.get_variable_name(data)),
                    "class": _safe(obj.get_class().get_path_name()) if obj else "",
                }
            )
    except Exception as exc:
        details["errors"].append("components: " + _safe(exc))
    try:
        graphs = unreal.BlueprintEditorLibrary.list_graphs(asset) or []
    except Exception:
        graphs = []
    for graph in graphs:
        graph_name = _safe(graph.get_name())
        graph_row = {"name": graph_name, "nodes": [], "errors": []}
        try:
            editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(asset, graph_name)
            nodes = editor.list_all_nodes() if editor else []
            for node in nodes or []:
                node_name = _safe(node.get_name())
                node_row = {
                    "name": node_name,
                    "title": _node_title(unreal, node),
                    "class": _safe(node.get_class().get_path_name()),
                    "pins": [],
                }
                for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
                    try:
                        connected = unreal.BlueprintGraphPinLibrary.list_connected_pins(pin) or []
                    except Exception:
                        connected = []
                    links = []
                    for other in connected:
                        try:
                            owner = unreal.BlueprintGraphPinLibrary.get_owning_node(other)
                            links.append(
                                {
                                    "node": _safe(owner.get_name()) if owner else "",
                                    "pin": _safe(unreal.BlueprintGraphPinLibrary.get_pin_name(other)),
                                }
                            )
                        except Exception:
                            continue
                    try:
                        pin_name = _safe(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
                    except Exception:
                        pin_name = ""
                    try:
                        pin_value = _safe(unreal.BlueprintGraphPinLibrary.get_pin_value(pin))
                    except Exception:
                        pin_value = ""
                    node_row["pins"].append(
                        {
                            "name": pin_name,
                            "direction": _pin_direction(unreal, pin),
                            "value": pin_value,
                            "links": links,
                        }
                    )
                graph_row["nodes"].append(node_row)
        except Exception as exc:
            graph_row["errors"].append(_safe(exc))
        graph_row["fingerprint"] = _hash(graph_row["nodes"])
        details["graphs"].append(graph_row)
    details["fingerprint"] = _hash(details)
    return details


def _animation_details(unreal, asset_path: str, asset: Any) -> dict[str, Any]:
    details = {"asset_path": asset_path, "kind": "animation", "skeleton": "", "probe": {}}
    try:
        skeleton = asset.get_editor_property("skeleton")
        details["skeleton"] = _safe(skeleton.get_path_name()) if skeleton else ""
    except Exception:
        pass
    library = getattr(unreal, "AIStudioBridgeLibrary", None)
    if library and hasattr(library, "inspect_animation_sequence"):
        try:
            details["probe"] = json.loads(library.inspect_animation_sequence(asset))
        except Exception as exc:
            details["probe"] = {"ok": False, "error": _safe(exc)}
    details["fingerprint"] = _hash(details)
    return details


def collect_semantic_project_batch(
    cursor: int = 0,
    batch_size: int = 250,
    detail_paths: list[str] | None = None,
    include_dependencies: bool = True,
) -> dict[str, Any]:
    """Collect one deterministic asset-catalog batch plus requested deep details."""

    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = sorted(
        list(registry.get_assets_by_path("/Game", recursive=True) or []),
        key=lambda row: _safe(row.package_name),
    )
    start = max(0, int(cursor or 0))
    size = max(1, min(int(batch_size or 250), 1000))
    selected = assets[start : start + size]
    rows = []
    dependency_options = unreal.AssetRegistryDependencyOptions()
    for data in selected:
        package_name = _safe(data.package_name)
        tags = _asset_tags(data)
        dependencies = []
        if include_dependencies:
            try:
                dependencies = [_safe(value) for value in registry.get_dependencies(package_name, dependency_options) or []]
            except Exception:
                dependencies = []
        row = {
            "package_name": package_name,
            "package_path": _safe(data.package_path),
            "asset_name": _safe(data.asset_name),
            "class_name": _asset_class_name(data),
            "tags": tags,
            "dependencies": dependencies,
        }
        row["fingerprint"] = _hash(
            {"package_name": package_name, "class_name": row["class_name"], "tags": tags}
        )
        rows.append(row)

    details = []
    for asset_path in dict.fromkeys(str(value) for value in detail_paths or [] if value):
        try:
            asset = load_asset(unreal, asset_path)
            if asset is None:
                details.append({"asset_path": asset_path, "kind": "missing", "error": "Asset could not be loaded."})
                continue
            class_name = _safe(asset.get_class().get_name())
            if "Blueprint" in class_name:
                details.append(_blueprint_details(unreal, asset_path, asset))
            elif class_name in {"AnimSequence", "AnimMontage", "BlendSpace", "PoseAsset"}:
                details.append(_animation_details(unreal, asset_path, asset))
            else:
                details.append(
                    {
                        "asset_path": asset_path,
                        "kind": "asset_detail",
                        "class_name": class_name,
                        "fingerprint": _hash({"asset_path": asset_path, "class_name": class_name}),
                    }
                )
        except Exception as exc:
            details.append({"asset_path": asset_path, "kind": "error", "error": _safe(exc)})
    next_cursor = start + len(selected)
    return {
        "ok": True,
        "cursor": start,
        "next_cursor": next_cursor,
        "total_assets": len(assets),
        "complete": next_cursor >= len(assets),
        "assets": rows,
        "details": details,
        "engine_version": _safe(unreal.SystemLibrary.get_engine_version()),
        "project_dir": _safe(unreal.Paths.project_dir()),
        "engine_dir": _safe(unreal.Paths.convert_relative_path_to_full(unreal.Paths.engine_dir())),
    }


def collect_semantic_asset_details(asset_paths: list[str]) -> dict[str, Any]:
    """Deeply inspect selected assets without rescanning the full catalog."""

    import unreal

    details = []
    for asset_path in dict.fromkeys(str(value) for value in asset_paths or [] if value):
        try:
            asset = load_asset(unreal, asset_path)
            if asset is None:
                details.append({"asset_path": asset_path, "kind": "missing", "error": "Asset could not be loaded."})
                continue
            class_name = _safe(asset.get_class().get_name())
            if "Blueprint" in class_name:
                details.append(_blueprint_details(unreal, asset_path, asset))
            elif class_name in {"AnimSequence", "AnimMontage", "BlendSpace", "PoseAsset"}:
                details.append(_animation_details(unreal, asset_path, asset))
            else:
                details.append(
                    {
                        "asset_path": asset_path,
                        "kind": "asset_detail",
                        "class_name": class_name,
                        "fingerprint": _hash({"asset_path": asset_path, "class_name": class_name}),
                    }
                )
        except Exception as exc:
            details.append({"asset_path": asset_path, "kind": "error", "error": _safe(exc)})
    return {"ok": True, "details": details}
