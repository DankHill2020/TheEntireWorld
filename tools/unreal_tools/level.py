"""Loaded-level scan helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _component_summary(component):
    try:
        return {
            "name": component.get_name(),
            "class": component.get_class().get_name(),
            "path": component.get_path_name(),
            "tags": [str(tag) for tag in getattr(component, "component_tags", [])],
        }
    except Exception as exc:
        return {"error": str(exc)}


def _actor_summary(unreal, actor):
    components = []
    try:
        components = [_component_summary(c) for c in actor.get_components_by_class(unreal.ActorComponent)]
    except Exception:
        pass

    try:
        bounds_origin, bounds_extent = actor.get_actor_bounds(False)
        bounds = {
            "origin": [bounds_origin.x, bounds_origin.y, bounds_origin.z],
            "extent": [bounds_extent.x, bounds_extent.y, bounds_extent.z],
        }
    except Exception:
        bounds = {}

    return {
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "path": actor.get_path_name(),
        "tags": [str(tag) for tag in getattr(actor, "tags", [])],
        "folder_path": str(actor.get_folder_path()) if hasattr(actor, "get_folder_path") else "",
        "hidden": bool(actor.is_hidden_ed()) if hasattr(actor, "is_hidden_ed") else False,
        "components": components,
        "bounds": bounds,
    }


def scan_loaded_level(include_components=True, max_actors=2000):
    """Return JSON-serializable facts about the currently loaded editor level."""
    import unreal

    editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = editor_subsystem.get_editor_world() if editor_subsystem else None
    level_name = world.get_name() if world else ""
    level_path = world.get_outer().get_path_name() if world and world.get_outer() else ""

    actors = []
    class_counts = {}
    component_class_counts = {}
    selected = []

    try:
        all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    except Exception:
        all_actors = []

    for actor in all_actors[: int(max_actors or 2000)]:
        item = _actor_summary(unreal, actor) if include_components else {
            "name": actor.get_name(),
            "label": actor.get_actor_label(),
            "class": actor.get_class().get_name(),
            "path": actor.get_path_name(),
            "tags": [str(tag) for tag in getattr(actor, "tags", [])],
        }
        actors.append(item)
        class_counts[item["class"]] = class_counts.get(item["class"], 0) + 1
        for component in item.get("components", []):
            cclass = component.get("class")
            if cclass:
                component_class_counts[cclass] = component_class_counts.get(cclass, 0) + 1

    try:
        selected = [actor.get_path_name() for actor in unreal.EditorLevelLibrary.get_selected_level_actors()]
    except Exception:
        selected = []

    result = {
        "current_level": level_path,
        "level_name": level_name,
        "actor_count": len(all_actors),
        "returned_actor_count": len(actors),
        "selected_actors": selected,
        "class_counts": class_counts,
        "component_class_counts": component_class_counts,
        "actors": actors,
        "warnings": [],
    }
    if len(all_actors) > len(actors):
        result["warnings"].append(f"Actor list truncated at {len(actors)} of {len(all_actors)}.")
    return json.dumps(result, indent=2, default=str)


def _all_level_actors(unreal):
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if subsystem and hasattr(subsystem, "get_all_level_actors"):
            return list(subsystem.get_all_level_actors() or [])
    except Exception:
        pass
    try:
        return list(unreal.EditorLevelLibrary.get_all_level_actors() or [])
    except Exception:
        return []


def resolve_actor(query="selected", allow_asset_lookup=True):
    """Resolve a name/label/path/tag/Blueprint or mesh asset name to level actors."""
    import json
    import unreal

    text = str(query or "selected").strip()
    q = text.lower()
    result = {"query": text, "matches": [], "warnings": []}

    def actor_handle(actor, source=""):
        try:
            return {
                "name": actor.get_name(),
                "label": actor.get_actor_label(),
                "class": actor.get_class().get_name(),
                "path": actor.get_path_name(),
                "tags": [str(t) for t in getattr(actor, "tags", [])],
                "source": source,
            }
        except Exception as exc:
            return {"error": str(exc), "source": source}

    if q in {"", "selected", "selection", "current", "same", "that", "it"}:
        try:
            subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actors = list(subsystem.get_selected_level_actors() or []) if subsystem else []
        except Exception:
            actors = list(unreal.EditorLevelLibrary.get_selected_level_actors() or [])
        result["matches"] = [actor_handle(a, "selected") for a in actors]
        return json.dumps(result, indent=2, default=str)

    actors = _all_level_actors(unreal)
    scored = []
    for actor in actors:
        try:
            hay = " ".join(
                [
                    actor.get_name(),
                    actor.get_actor_label(),
                    actor.get_path_name(),
                    actor.get_class().get_name(),
                    " ".join(str(t) for t in getattr(actor, "tags", [])),
                ]
            ).lower()
            score = 0
            if q in {actor.get_name().lower(), actor.get_actor_label().lower(), actor.get_path_name().lower()}:
                score += 100
            if q in hay:
                score += 25
            if q.replace("_", "") in hay.replace("_", ""):
                score += 10
            if score:
                scored.append((score, actor))
        except Exception:
            pass

    if allow_asset_lookup and not scored:
        try:
            from unreal_tools.assets import find_asset_path_by_name
            asset_path = find_asset_path_by_name(text)
            asset = unreal.EditorAssetLibrary.load_asset(asset_path) if asset_path else None
        except Exception:
            asset = None
        if asset:
            for actor in actors:
                try:
                    generated = asset.generated_class() if hasattr(asset, "generated_class") else None
                    if generated and actor.get_class().is_child_of(generated):
                        scored.append((90, actor))
                        continue
                except Exception:
                    pass
                try:
                    asset_pkg = asset.get_path_name().split(".", 1)[0].lower()
                    for comp in actor.get_components_by_class(unreal.ActorComponent) or []:
                        for prop in ("skeletal_mesh", "static_mesh", "mesh", "animation", "niagara_system"):
                            try:
                                value = comp.get_editor_property(prop)
                                if value and hasattr(value, "get_path_name") and value.get_path_name().split(".", 1)[0].lower() == asset_pkg:
                                    scored.append((80, actor))
                                    raise StopIteration
                            except StopIteration:
                                raise
                            except Exception:
                                pass
                except StopIteration:
                    pass
                except Exception:
                    pass

    scored.sort(key=lambda item: item[0], reverse=True)
    seen = set()
    for score, actor in scored[:20]:
        handle = actor_handle(actor, "level_resolver")
        if handle.get("path") in seen:
            continue
        seen.add(handle.get("path"))
        handle["score"] = score
        result["matches"].append(handle)
    return json.dumps(result, indent=2, default=str)


def select_actors_by_query(query):
    """Resolve actor query/queries to real Actor objects and select them in-editor."""
    import json
    import unreal

    queries = query if isinstance(query, list) else [query]
    all_actors = _all_level_actors(unreal)
    path_to_actor = {a.get_path_name(): a for a in all_actors if hasattr(a, "get_path_name")}
    selected = []
    resolved = []
    for item in queries:
        data = json.loads(resolve_actor(item))
        if not data.get("matches"):
            continue
        handle = data["matches"][0]
        actor = path_to_actor.get(handle.get("path"))
        if actor and actor not in selected:
            selected.append(actor)
            resolved.append(handle)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if subsystem:
        subsystem.set_selected_level_actors(selected)
    else:
        unreal.EditorLevelLibrary.set_selected_level_actors(selected)
    return json.dumps({"ok": True, "selected_count": len(selected), "selected_actors": resolved}, indent=2, default=str)


def get_selected_actors():
    import unreal

    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = list(subsystem.get_selected_level_actors() or []) if subsystem else []
    except Exception:
        actors = list(unreal.EditorLevelLibrary.get_selected_level_actors() or [])
    return json.dumps({
        "ok": True,
        "selected_actors": [_actor_summary(unreal, actor) for actor in actors],
        "count": len(actors),
    }, indent=2, default=str)


def create_validation_map(map_path="/Game/Developers/AI_Validation/Disposable_TestMap", spawn_actors=None, test_steps=None, save=True):
    """Create/open a disposable validation map and return editor readback evidence."""
    import unreal

    spawn_actors = list(spawn_actors or [])
    test_steps = list(test_steps or [])
    normalized = str(map_path or "/Game/Developers/AI_Validation/Disposable_TestMap").split(".", 1)[0]
    warnings = []
    created_or_loaded = False
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(normalized):
            loaded = unreal.EditorLevelLibrary.load_level(normalized)
            created_or_loaded = bool(loaded)
        elif hasattr(unreal.EditorLevelLibrary, "new_level"):
            created_or_loaded = bool(unreal.EditorLevelLibrary.new_level(normalized))
        else:
            return json.dumps(
                {
                    "ok": False,
                    "status": "level_creation_api_unavailable",
                    "map_path": normalized,
                    "required_api": "EditorLevelLibrary.new_level",
                },
                indent=2,
            )
    except Exception as exc:
        return json.dumps({"ok": False, "status": "map_create_or_load_failed", "map_path": normalized, "error": str(exc)}, indent=2)

    spawned = []
    for actor_spec in spawn_actors:
        if isinstance(actor_spec, str):
            actor_spec = {"class_path": actor_spec}
        class_path = str(actor_spec.get("class_path") or actor_spec.get("class") or "")
        location = actor_spec.get("location") or [0.0, 0.0, 0.0]
        if not class_path:
            continue
        try:
            cls = unreal.load_class(None, class_path)
            if not cls:
                warnings.append(f"actor class not found: {class_path}")
                continue
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
                cls,
                unreal.Vector(float(location[0]), float(location[1]), float(location[2])),
            )
            if actor:
                spawned.append(actor.get_path_name())
        except Exception as exc:
            warnings.append(f"spawn failed for {class_path}: {exc}")
    saved = False
    if save:
        try:
            saved = bool(unreal.EditorLoadingAndSavingUtils.save_current_level())
        except Exception as exc:
            warnings.append(f"save_current_level warning: {exc}")
    return json.dumps(
        {
            "ok": bool(created_or_loaded),
            "status": "validation_map_ready" if created_or_loaded else "validation_map_not_ready",
            "map_path": normalized,
            "spawned_actors": spawned,
            "test_steps": test_steps,
            "saved": saved,
            "warnings": warnings,
        },
        indent=2,
        default=str,
    )


def delete_actor(actor_query, dry_run=False):
    import unreal

    data = json.loads(resolve_actor(actor_query))
    if not data.get("matches"):
        return json.dumps({"ok": False, "actor_query": actor_query, "error": "actor_not_found"}, indent=2)
    target_path = data["matches"][0].get("path")
    actor = next((item for item in _all_level_actors(unreal) if item.get_path_name() == target_path), None)
    if not actor:
        return json.dumps({"ok": False, "actor_query": actor_query, "error": "actor_object_not_resolved", "match": data["matches"][0]}, indent=2)
    deleted = False
    if not dry_run:
        try:
            subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            deleted = bool(subsystem.destroy_actor(actor)) if subsystem else bool(unreal.EditorLevelLibrary.destroy_actor(actor))
        except Exception as exc:
            return json.dumps({"ok": False, "actor_query": actor_query, "error": str(exc), "match": data["matches"][0]}, indent=2)
    return json.dumps({
        "ok": bool(dry_run or deleted),
        "actor_query": actor_query,
        "actor_path": target_path,
        "deleted": deleted,
        "dry_run": bool(dry_run),
    }, indent=2, default=str)


def organize_actors(actor_specs, save=True):
    """
        Organizes existing actors with labels, Outliner folders, tags, and visibility.

    :param actor_specs: actor queries and requested organization properties
    :param save: whether to save the current level
    :return: JSON mutation and exact actor readback receipt
    """
    import unreal

    specs = list(actor_specs or [])
    if not specs:
        raise ValueError("At least one actor organization specification is required")
    actors_by_path = {
        actor.get_path_name(): actor
        for actor in _all_level_actors(unreal)
        if actor is not None
    }
    resolved = []
    targeted_paths = set()
    for index, raw_spec in enumerate(specs):
        if not isinstance(raw_spec, dict):
            raise ValueError("Actor organization specifications must be objects")
        query = str(raw_spec.get("query") or raw_spec.get("actor") or "").strip()
        if not query:
            raise ValueError(f"Actor organization specification {index} requires query")
        matches = json.loads(resolve_actor(query, allow_asset_lookup=False)).get("matches") or []
        if not matches:
            raise ValueError("Actor query did not resolve: " + query)
        exact_matches = [
            match for match in matches
            if query.casefold() in {
                str(match.get("name") or "").casefold(),
                str(match.get("label") or "").casefold(),
                str(match.get("path") or "").casefold(),
            }
        ]
        chosen_matches = exact_matches or matches
        if len(chosen_matches) != 1:
            labels = ", ".join(str(match.get("label") or match.get("name")) for match in chosen_matches[:5])
            raise ValueError(f"Actor query is ambiguous: {query} ({labels})")
        actor_path = str(chosen_matches[0].get("path") or "")
        actor = actors_by_path.get(actor_path)
        if actor is None:
            raise ValueError("Resolved actor object is unavailable: " + actor_path)
        if actor_path in targeted_paths:
            raise ValueError("Actor is targeted more than once: " + actor_path)
        targeted_paths.add(actor_path)
        folder = str(raw_spec.get("folder") or raw_spec.get("folder_path") or "").strip()
        label = str(raw_spec.get("label") or "").strip()
        add_tags = [str(value).strip() for value in list(raw_spec.get("add_tags") or []) if str(value).strip()]
        remove_tags = {str(value).strip().casefold() for value in list(raw_spec.get("remove_tags") or []) if str(value).strip()}
        resolved.append({
            "query": query,
            "actor": actor,
            "actor_path": actor_path,
            "folder": folder,
            "set_folder": "folder" in raw_spec or "folder_path" in raw_spec,
            "label": label,
            "set_label": "label" in raw_spec,
            "add_tags": add_tags,
            "remove_tags": remove_tags,
            "hidden": bool(raw_spec.get("hidden")) if "hidden" in raw_spec else None,
        })

    receipts = []
    with unreal.ScopedEditorTransaction("Tech Connector: Organize Level Actors"):
        for item in resolved:
            actor = item["actor"]
            actor.modify()
            if item["set_label"]:
                if not item["label"]:
                    raise ValueError("Actor labels cannot be blank")
                actor.set_actor_label(item["label"], True)
            if item["set_folder"]:
                actor.set_folder_path(unreal.Name(item["folder"]))
            current_tags = [str(value) for value in list(actor.get_editor_property("tags") or [])]
            next_tags = [
                value for value in current_tags
                if value.casefold() not in item["remove_tags"]
            ]
            existing_folded = {value.casefold() for value in next_tags}
            for value in item["add_tags"]:
                if value.casefold() not in existing_folded:
                    next_tags.append(value)
                    existing_folded.add(value.casefold())
            actor.set_editor_property("tags", [unreal.Name(value) for value in next_tags])
            if item["hidden"] is not None:
                actor.set_is_temporarily_hidden_in_editor(item["hidden"])
            receipts.append({
                "query": item["query"],
                "actor_path": item["actor_path"],
                "label": str(actor.get_actor_label()),
                "folder_path": str(actor.get_folder_path()),
                "tags": [str(value) for value in list(actor.get_editor_property("tags") or [])],
                "hidden": bool(actor.is_hidden_ed()),
            })

    saved = bool(unreal.EditorLoadingAndSavingUtils.save_current_level()) if save else False
    verified = len(receipts) == len(resolved) and (saved or not save)
    return json.dumps({
        "ok": verified,
        "status": "actors_organized_and_level_saved" if saved else "actors_organized",
        "actor_count": len(receipts),
        "actors": receipts,
        "saved": saved,
    }, indent=2, default=str)
