"""Animation helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _asset_path(asset):
    try:
        return str(asset.get_path_name())
    except Exception:
        return str(asset or "")


def _split_package_asset_path(asset_path):
    package_path = str(asset_path or "").split(".", 1)[0].rstrip("/")
    folder, _, asset_name = package_path.rpartition("/")
    if not folder or not asset_name:
        raise ValueError(f"Expected an Unreal package path, got {asset_path!r}")
    return folder, asset_name, package_path


def _load_anim_blueprint(unreal, anim_bp_path):
    asset = unreal.EditorAssetLibrary.load_asset(str(anim_bp_path or ""))
    if asset is None:
        raise ValueError(f"Animation Blueprint not found: {anim_bp_path}")
    return asset


def _animation_skeleton(animation):
    for name in ("skeleton", "target_skeleton"):
        try:
            value = animation.get_editor_property(name)
            if value:
                return value
        except Exception:
            pass
    return getattr(animation, "skeleton", None)


def _skeletal_meshes_for_skeleton(unreal, skeleton):
    """Return stable project SkeletalMesh candidates that use ``skeleton``."""
    if not skeleton:
        return []
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    candidates = []
    for data in registry.get_assets_by_path("/Game/", recursive=True):
        try:
            if str(data.asset_class_path.asset_name) != "SkeletalMesh":
                continue
            mesh = data.get_asset()
            if mesh and mesh.get_editor_property("skeleton") == skeleton:
                candidates.append(_asset_path(mesh))
        except Exception:
            continue
    return sorted(dict.fromkeys(candidates), key=str.lower)


def _sequence_metric(animation, property_names, method_names=()):
    for name in property_names:
        try:
            return animation.get_editor_property(name)
        except Exception:
            pass
    for name in method_names:
        method = getattr(animation, name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                pass
    return None


def resolve_animation_target(target_hint="", directory="/Game/"):
    """Resolve one target mesh, Skeleton, and AnimBP from live project assets."""
    import unreal

    hint_tokens = [
        token.lower()
        for token in str(target_hint or "").replace("-", "_").split("_")
        if token.strip()
    ]
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    candidates = []
    for data in registry.get_assets_by_path(str(directory or "/Game/"), recursive=True):
        try:
            class_name = str(data.asset_class_path.asset_name)
            object_path = str(data.get_soft_object_path())
            asset_name = str(data.asset_name)
        except Exception:
            continue
        if class_name not in {"SkeletalMesh", "Skeleton", "AnimBlueprint"}:
            continue
        haystack = f"{asset_name} {object_path}".lower()
        score = sum(2 for token in hint_tokens if token in haystack)
        if "manny" in hint_tokens and "manny" in haystack:
            score += 5
        candidates.append({
            "class": class_name,
            "asset_name": asset_name,
            "object_path": object_path,
            "score": score,
        })
    candidates.sort(key=lambda row: (row["score"], row["class"] == "SkeletalMesh"), reverse=True)
    matching = [row for row in candidates if row["score"] > 0] if hint_tokens else candidates
    by_class = {
        class_name: [row for row in matching if row["class"] == class_name]
        for class_name in ("SkeletalMesh", "Skeleton", "AnimBlueprint")
    }
    mesh_path = by_class["SkeletalMesh"][0]["object_path"] if by_class["SkeletalMesh"] else ""
    skeleton_path = by_class["Skeleton"][0]["object_path"] if by_class["Skeleton"] else ""
    if mesh_path:
        mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        try:
            mesh_skeleton = mesh.get_editor_property("skeleton")
            skeleton_path = _asset_path(mesh_skeleton) or skeleton_path
        except Exception:
            pass
    result = {
        "ok": bool(mesh_path and skeleton_path),
        "status": "resolved" if mesh_path and skeleton_path else "target_resolution_required",
        "target_hint": str(target_hint or ""),
        "target_skeletal_mesh_path": mesh_path,
        "target_skeleton_path": skeleton_path,
        "target_anim_blueprint_path": (
            by_class["AnimBlueprint"][0]["object_path"] if by_class["AnimBlueprint"] else ""
        ),
        "candidates": matching[:20],
    }
    return json.dumps(result, indent=2, default=str)


def set_slot_animation(anim_bp_path, slot_name, animation_path):
    """
    Sets an animation on a montage slot compatible with an Animation Blueprint.

    :param anim_bp_path: Animation Blueprint used to resolve the target skeleton.
    :param slot_name: montage slot name to assign.
    :param animation_path: source AnimSequence asset path.
    :return: JSON operation result with asset and slot readback.
    """
    import unreal

    anim_blueprint = _load_anim_blueprint(unreal, anim_bp_path)
    animation = unreal.EditorAssetLibrary.load_asset(str(animation_path or ""))
    if animation is None:
        raise ValueError(f"Animation asset not found: {animation_path}")
    requested_slot = str(slot_name or "").strip()
    if not requested_slot:
        raise ValueError("A non-empty montage slot name is required.")

    blueprint_skeleton = None
    try:
        blueprint_skeleton = anim_blueprint.get_editor_property("target_skeleton")
    except Exception:
        pass
    animation_skeleton = _animation_skeleton(animation)
    if blueprint_skeleton and animation_skeleton and blueprint_skeleton != animation_skeleton:
        return json.dumps(
            {
                "ok": False,
                "status": "skeleton_mismatch",
                "anim_blueprint": _asset_path(anim_blueprint),
                "animation": _asset_path(animation),
            },
            indent=2,
        )

    source_package = str(animation_path or "").split(".", 1)[0]
    source_folder, _, source_name = source_package.rpartition("/")
    montage_name = f"{source_name}_{requested_slot}_Montage"
    montage_path = f"{source_folder}/{montage_name}"
    montage = unreal.EditorAssetLibrary.load_asset(montage_path)
    created = False
    if montage is None:
        factory_class = getattr(unreal, "AnimMontageFactory", None)
        montage_class = getattr(unreal, "AnimMontage", None)
        if factory_class is None or montage_class is None:
            return json.dumps(
                {
                    "ok": False,
                    "status": "anim_montage_factory_unavailable",
                    "missing": [
                        name
                        for name, value in (
                            ("AnimMontageFactory", factory_class),
                            ("AnimMontage", montage_class),
                        )
                        if value is None
                    ],
                },
                indent=2,
            )
        factory = factory_class()
        for property_name, value in (
            ("source_animation", animation),
            ("target_skeleton", animation_skeleton or blueprint_skeleton),
        ):
            if value is None:
                continue
            try:
                factory.set_editor_property(property_name, value)
            except Exception:
                pass
        montage = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            montage_name,
            source_folder,
            montage_class,
            factory,
        )
        created = montage is not None
    if montage is None:
        return json.dumps(
            {"ok": False, "status": "montage_creation_failed", "asset_path": montage_path},
            indent=2,
        )

    try:
        tracks = list(montage.get_editor_property("slot_anim_tracks") or [])
        for track in tracks:
            track.set_editor_property("slot_name", requested_slot)
        if tracks:
            montage.set_editor_property("slot_anim_tracks", tracks)
        slot_readback = [str(track.get_editor_property("slot_name")) for track in tracks]
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "status": "slot_track_update_failed",
                "asset_path": montage_path,
                "error": str(exc),
            },
            indent=2,
        )
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(montage, False))
    return json.dumps(
        {
            "ok": bool(saved and requested_slot in slot_readback),
            "status": "saved" if saved else "save_failed",
            "asset_path": _asset_path(montage).split(".", 1)[0],
            "anim_blueprint": _asset_path(anim_blueprint).split(".", 1)[0],
            "animation": _asset_path(animation).split(".", 1)[0],
            "slot_name": requested_slot,
            "slot_readback": slot_readback,
            "created": created,
            "saved": saved,
        },
        indent=2,
    )


def inspect_imported_animation_pipeline(
    imported_paths,
    target_skeleton_path="",
    target_skeletal_mesh_path="",
):
    """Inspect imported animation timing, root motion, and skeleton compatibility."""
    import unreal

    target_skeleton = (
        unreal.EditorAssetLibrary.load_asset(str(target_skeleton_path))
        if target_skeleton_path
        else None
    )
    if target_skeleton is None and target_skeletal_mesh_path:
        mesh = unreal.EditorAssetLibrary.load_asset(str(target_skeletal_mesh_path))
        try:
            target_skeleton = mesh.get_editor_property("skeleton")
        except Exception:
            target_skeleton = None
    rows = []
    source_skeletons = {}
    for path in list(imported_paths or []):
        asset = unreal.EditorAssetLibrary.load_asset(str(path))
        if not asset:
            rows.append({"asset_path": str(path), "ok": False, "status": "asset_not_found"})
            continue
        class_name = str(asset.get_class().get_name())
        row = {"asset_path": str(path), "class": class_name, "ok": True}
        if class_name == "AnimSequence":
            skeleton = _animation_skeleton(asset)
            skeleton_path = _asset_path(skeleton)
            if skeleton_path:
                source_skeletons[skeleton_path] = skeleton
            frame_count = _sequence_metric(
                asset,
                ("number_of_sampled_keys", "number_of_frames"),
                ("get_number_of_sampled_keys",),
            )
            row.update({
                "skeleton_path": skeleton_path,
                "sequence_length": _sequence_metric(
                    asset,
                    ("sequence_length",),
                    ("get_play_length",),
                ),
                "frame_count": frame_count,
                "root_motion_enabled": bool(_sequence_metric(
                    asset,
                    ("enable_root_motion", "force_root_lock"),
                )),
                "compatible_with_target": bool(target_skeleton and skeleton == target_skeleton),
            })
            row["retarget_required"] = bool(target_skeleton and skeleton != target_skeleton)
        rows.append(row)
    animations = [row for row in rows if row.get("class") == "AnimSequence"]
    skeletal_meshes = [row for row in rows if row.get("class") == "SkeletalMesh"]
    target_mesh_candidates = _skeletal_meshes_for_skeleton(unreal, target_skeleton)
    resolved_target_mesh = str(target_skeletal_mesh_path or "")
    if not resolved_target_mesh and target_mesh_candidates:
        resolved_target_mesh = target_mesh_candidates[0]
    source_mesh_candidates = []
    for source_skeleton in source_skeletons.values():
        source_mesh_candidates.extend(
            _skeletal_meshes_for_skeleton(unreal, source_skeleton)
        )
    source_mesh_candidates = sorted(
        dict.fromkeys(source_mesh_candidates),
        key=str.lower,
    )
    resolved_source_mesh = (
        skeletal_meshes[0]["asset_path"]
        if skeletal_meshes
        else source_mesh_candidates[0]
        if source_mesh_candidates
        else ""
    )
    result = {
        "ok": bool(animations) and all(row.get("ok") for row in rows),
        "status": "inspected" if animations else "no_animation_sequence_imported",
        "target_skeleton_path": _asset_path(target_skeleton),
        "target_skeletal_mesh_path": resolved_target_mesh,
        "target_skeletal_mesh_candidates": target_mesh_candidates,
        "assets": rows,
        "animation_paths": [row["asset_path"] for row in animations],
        "source_skeletal_mesh_path": resolved_source_mesh,
        "source_skeletal_mesh_candidates": source_mesh_candidates,
        "retarget_required": any(row.get("retarget_required") for row in animations),
        "compatible_animation_paths": [
            row["asset_path"] for row in animations if row.get("compatible_with_target")
        ],
    }
    result["compatibility_report"] = dict(result)
    return json.dumps(result, indent=2, default=str)


def retarget_imported_animations_if_needed(
    compatibility_report,
    source_skeletal_mesh_path="",
    target_skeletal_mesh_path="",
    output_path="/Game/Animations/Retargeted",
    retargeter_path="",
):
    """Retarget only incompatible imported AnimSequences and preserve compatible ones."""
    report = (
        json.loads(compatibility_report)
        if isinstance(compatibility_report, str)
        else dict(compatibility_report or {})
    )
    if not report.get("ok"):
        return json.dumps({
            "ok": False,
            "status": "compatibility_report_invalid",
            "compatibility_report": report,
        }, indent=2, default=str)
    source_skeletal_mesh_path = str(
        source_skeletal_mesh_path
        or report.get("source_skeletal_mesh_path")
        or ""
    )
    target_skeletal_mesh_path = str(
        target_skeletal_mesh_path
        or report.get("target_skeletal_mesh_path")
        or ""
    )
    required_rows = [
        row
        for row in list(report.get("assets") or [])
        if row.get("class") == "AnimSequence" and row.get("retarget_required")
    ]
    if required_rows and (
        not source_skeletal_mesh_path or not target_skeletal_mesh_path
    ):
        return json.dumps({
            "ok": False,
            "status": "retarget_target_resolution_required",
            "missing": [
                name
                for name, value in (
                    ("source_skeletal_mesh_path", source_skeletal_mesh_path),
                    ("target_skeletal_mesh_path", target_skeletal_mesh_path),
                )
                if not value
            ],
            "source_skeletal_mesh_candidates": list(
                report.get("source_skeletal_mesh_candidates") or []
            ),
            "target_skeletal_mesh_candidates": list(
                report.get("target_skeletal_mesh_candidates") or []
            ),
            "retarget_required_assets": [
                row.get("asset_path") for row in required_rows
            ],
        }, indent=2, default=str)
    outputs = list(report.get("compatible_animation_paths") or [])
    retarget_results = []
    for row in list(report.get("assets") or []):
        if row.get("class") != "AnimSequence" or not row.get("retarget_required"):
            continue
        raw = retarget_animation(
            row.get("asset_path"),
            source_skeletal_mesh_path,
            target_skeletal_mesh_path,
            output_path,
            retargeter_path=retargeter_path,
            save=True,
        )
        result = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        retarget_results.append(result)
        produced = (
            result.get("output_asset")
            or result.get("asset_path")
            or result.get("retargeted_animation")
        )
        if produced:
            outputs.append(str(produced))
    required_count = sum(
        1 for row in list(report.get("assets") or [])
        if row.get("class") == "AnimSequence" and row.get("retarget_required")
    )
    result = {
        "ok": len(retarget_results) == required_count and all(
            row.get("ok") for row in retarget_results
        ),
        "status": "retargeted" if required_count else "retarget_not_required",
        "retarget_required_count": required_count,
        "retarget_results": retarget_results,
        "animation_paths": list(dict.fromkeys(outputs)),
    }
    return json.dumps(result, indent=2, default=str)


def report_animation_pipeline_assets(
    imported_paths,
    animation_paths,
    target_skeleton_path="",
    target_anim_blueprint_path="",
):
    """Return final asset existence, ownership, and compatibility evidence."""
    import unreal

    paths = list(dict.fromkeys([
        *[str(path) for path in imported_paths or []],
        *[str(path) for path in animation_paths or []],
    ]))
    rows = []
    for path in paths:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        rows.append({
            "asset_path": path,
            "exists": bool(asset),
            "class": str(asset.get_class().get_name()) if asset else "",
            "saved": bool(unreal.EditorAssetLibrary.does_asset_exist(path)),
        })
    return json.dumps({
        "ok": bool(rows) and all(row["exists"] and row["saved"] for row in rows),
        "status": "reported",
        "assets": rows,
        "target_skeleton_path": str(target_skeleton_path or ""),
        "target_anim_blueprint_path": str(target_anim_blueprint_path or ""),
        "errors": [row for row in rows if not row["exists"] or not row["saved"]],
    }, indent=2, default=str)


def find_compatible_animations(skeleton_path, directory="/Game/"):
    import unreal

    skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_path(directory, recursive=True)
    matches = []
    for data in assets:
        if str(data.asset_class_path.asset_name) != "AnimSequence":
            continue
        try:
            anim = data.get_asset()
            if getattr(anim, "skeleton", None) == skeleton:
                matches.append(str(data.object_path))
        except Exception:
            pass
    return json.dumps({"skeleton_path": skeleton_path, "animations": matches}, indent=2)


def create_or_update_animation_blueprint(skeleton_path, asset_path, template="locomotion"):
    """Create or reuse a base AnimBlueprint for a concrete Skeleton."""
    import unreal

    skeleton = unreal.EditorAssetLibrary.load_asset(str(skeleton_path or ""))
    if skeleton is None:
        return json.dumps(
            {
                "ok": False,
                "status": "skeleton_not_found",
                "skeleton_path": skeleton_path,
                "asset_path": asset_path,
            },
            indent=2,
        )

    folder, asset_name, package_path = _split_package_asset_path(asset_path)
    anim_bp = unreal.EditorAssetLibrary.load_asset(package_path)
    created = anim_bp is None
    if created:
        factory = unreal.AnimBlueprintFactory()
        factory.set_editor_property("target_skeleton", skeleton)
        factory.set_editor_property("parent_class", unreal.AnimInstance)
        anim_bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name,
            folder,
            unreal.AnimBlueprint,
            factory,
        )
    if anim_bp is None:
        return json.dumps(
            {
                "ok": False,
                "status": "create_failed",
                "skeleton_path": skeleton_path,
                "asset_path": package_path,
            },
            indent=2,
        )

    try:
        assigned_skeleton = anim_bp.get_editor_property("target_skeleton")
    except Exception:
        assigned_skeleton = None
    if assigned_skeleton and assigned_skeleton != skeleton:
        return json.dumps(
            {
                "ok": False,
                "status": "existing_asset_skeleton_mismatch",
                "asset_path": _asset_path(anim_bp),
                "expected_skeleton": _asset_path(skeleton),
                "actual_skeleton": _asset_path(assigned_skeleton),
            },
            indent=2,
        )

    unreal.BlueprintEditorLibrary.compile_blueprint(anim_bp)
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(anim_bp, False))
    graph_names = [
        str(value)
        for value in unreal.BlueprintEditorLibrary.list_graph_names(anim_bp) or []
    ]
    return json.dumps(
        {
            "ok": saved,
            "status": (
                "created_and_saved"
                if created and saved
                else "reused_and_saved"
                if saved
                else "save_failed"
            ),
            "created": created,
            "asset_path": _asset_path(anim_bp),
            "anim_bp_path": _asset_path(anim_bp),
            "skeleton_path": _asset_path(skeleton),
            "template": str(template or ""),
            "graph_names": graph_names,
            "saved": saved,
        },
        indent=2,
        default=str,
    )


def add_state_machine(anim_bp_path, state_machine_name):
    import unreal

    anim_bp = _load_anim_blueprint(unreal, anim_bp_path)
    return unreal.AIStudioBridgeLibrary.add_anim_graph_state_machine(
        anim_bp,
        str(state_machine_name),
    )


def add_state(
    anim_bp_path,
    state_machine_name,
    state_name,
    animation_asset_path="",
):
    import unreal

    anim_bp = _load_anim_blueprint(unreal, anim_bp_path)
    animation_asset = (
        unreal.EditorAssetLibrary.load_asset(str(animation_asset_path))
        if animation_asset_path
        else None
    )
    if animation_asset_path and animation_asset is None:
        raise ValueError(f"Animation asset not found: {animation_asset_path}")
    return unreal.AIStudioBridgeLibrary.add_anim_graph_state(
        anim_bp,
        str(state_machine_name),
        str(state_name),
        animation_asset,
    )


def add_transition_rule(
    anim_bp_path,
    state_machine_name,
    from_state,
    to_state,
    rule_expression,
):
    import unreal

    anim_bp = _load_anim_blueprint(unreal, anim_bp_path)
    return unreal.AIStudioBridgeLibrary.add_anim_graph_transition_rule(
        anim_bp,
        str(state_machine_name),
        str(from_state),
        str(to_state),
        str(rule_expression),
    )


def wire_state_machine_to_output_pose(anim_bp_path, state_machine_name):
    import unreal

    anim_bp = _load_anim_blueprint(unreal, anim_bp_path)
    return unreal.AIStudioBridgeLibrary.wire_anim_graph_output_pose(
        anim_bp,
        str(state_machine_name),
    )


def compile_and_save_anim_blueprint(anim_bp_path):
    import unreal

    anim_bp = _load_anim_blueprint(unreal, anim_bp_path)
    return unreal.AIStudioBridgeLibrary.compile_and_save_anim_blueprint(anim_bp)


def get_state_machine_graph(anim_bp_path, state_machine_name):
    import unreal

    anim_bp = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if not anim_bp:
        return json.dumps({"ok": False, "error": "anim_blueprint_not_found", "anim_bp_path": anim_bp_path}, indent=2)
    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "error": "AIStudioBridgeLibrary_unavailable", "anim_bp_path": anim_bp_path}, indent=2)
    raw = unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph(anim_bp)
    try:
        data = json.loads(raw)
    except Exception:
        data = {"ok": False, "raw": raw}
    graphs = [
        graph for graph in data.get("graphs", [])
        if str(graph.get("name", "")).lower() == str(state_machine_name).lower()
    ]
    return json.dumps({
        "ok": bool(data.get("ok")) and bool(graphs),
        "anim_bp_path": anim_bp_path,
        "state_machine_name": state_machine_name,
        "graphs": graphs,
        "source": "AIStudioBridge.inspect_anim_blueprint_graph",
    }, indent=2, default=str)


def add_anim_notify(animation_path, notify_name, notify_class="", time_ratio=0.0, save=True):
    import unreal

    animation = unreal.EditorAssetLibrary.load_asset(animation_path)
    if not animation:
        return json.dumps({"ok": False, "error": "animation_not_found", "animation_path": animation_path}, indent=2)
    library = getattr(unreal, "AnimationBlueprintLibrary", None)
    if not library or not hasattr(library, "add_anim_notify_event"):
        return json.dumps({"ok": False, "status": "api_unavailable", "api": "AnimationBlueprintLibrary.add_anim_notify_event"}, indent=2)
    try:
        length = float(animation.get_editor_property("sequence_length"))
    except Exception:
        length = 0.0
    time = max(0.0, min(1.0, float(time_ratio))) * length
    notify_cls = unreal.AnimNotify
    if notify_class:
        loaded = unreal.load_class(None, str(notify_class))
        if loaded:
            notify_cls = loaded
    event = library.add_anim_notify_event(animation, time, notify_cls)
    if event:
        try:
            event.set_editor_property("notify_name", str(notify_name))
        except Exception:
            pass
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(animation, False)
    return json.dumps({
        "ok": bool(event),
        "animation_path": animation_path,
        "notify_name": notify_name,
        "notify_class": str(notify_class or "AnimNotify"),
        "time": time,
        "saved": bool(save),
    }, indent=2, default=str)


def delete_state_from_state_machine(anim_bp_path, state_machine_name, state_name):
    import unreal

    anim_bp = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if not anim_bp:
        return json.dumps({"ok": False, "status": "anim_blueprint_not_found", "anim_bp_path": anim_bp_path}, indent=2)
    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable", "anim_bp_path": anim_bp_path}, indent=2)
    return unreal.AIStudioBridgeLibrary.delete_anim_graph_state(anim_bp, state_machine_name, state_name)


def delete_state_transition(anim_bp_path, from_state, to_state):
    import unreal

    anim_bp = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if not anim_bp:
        return json.dumps({"ok": False, "status": "anim_blueprint_not_found", "anim_bp_path": anim_bp_path}, indent=2)
    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable", "anim_bp_path": anim_bp_path}, indent=2)
    return unreal.AIStudioBridgeLibrary.delete_anim_graph_transition(anim_bp, "", from_state, to_state)


def rename_state(anim_bp_path, state_machine_name, old_state_name, new_state_name):
    import unreal

    anim_bp = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if not anim_bp:
        return json.dumps({"ok": False, "status": "anim_blueprint_not_found", "anim_bp_path": anim_bp_path}, indent=2)
    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable", "anim_bp_path": anim_bp_path}, indent=2)
    return unreal.AIStudioBridgeLibrary.rename_anim_graph_state(anim_bp, state_machine_name, old_state_name, new_state_name)


def set_state_transition_rule(anim_bp_path, from_state, to_state, condition_rule):
    import unreal

    anim_bp = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if not anim_bp:
        return json.dumps({"ok": False, "status": "anim_blueprint_not_found", "anim_bp_path": anim_bp_path}, indent=2)
    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable", "anim_bp_path": anim_bp_path}, indent=2)
    return unreal.AIStudioBridgeLibrary.set_anim_graph_transition_rule(anim_bp, "", from_state, to_state, condition_rule)


def synthesize_transition_rule_expression(anim_bp_path, state_machine_name, from_state, to_state, rule_expression):
    import unreal

    anim_bp = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if not anim_bp:
        return json.dumps({"ok": False, "status": "anim_blueprint_not_found", "anim_bp_path": anim_bp_path}, indent=2)
    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable", "anim_bp_path": anim_bp_path}, indent=2)
    return unreal.AIStudioBridgeLibrary.synthesize_anim_graph_transition_rule_expression(
        anim_bp,
        state_machine_name,
        from_state,
        to_state,
        rule_expression,
    )


def retarget_animation(
    source_animation,
    source_skeletal_mesh_path="",
    target_skeletal_mesh_path="",
    output_path="/Game/Animations/Retargeted",
    retargeter_path="",
    destination_suffix="_Retargeted",
    save=True,
):
    """Retarget an animation through an explicit or discoverable IK Retargeter."""
    if retargeter_path:
        from unreal_tools.retargeting import retarget_animation as _retarget_animation

        return json.dumps(
            _retarget_animation(
                source_animation,
                source_skeletal_mesh_path,
                target_skeletal_mesh_path,
                retargeter_path,
                output_path,
                destination_suffix=destination_suffix,
                save=save,
            ),
            indent=2,
            default=str,
        )
    try:
        from unreal_tools.retargeting import retarget_animation_with_matching_project_asset

        return json.dumps(
            retarget_animation_with_matching_project_asset(
                source_animation,
                source_skeletal_mesh_path,
                target_skeletal_mesh_path,
                output_path,
                destination_suffix=destination_suffix,
                save=save,
            ),
            indent=2,
            default=str,
        )
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "status": "retarget_adapter_failed",
                "source_animation": source_animation,
                "source_skeletal_mesh_path": source_skeletal_mesh_path,
                "target_skeletal_mesh_path": target_skeletal_mesh_path,
                "output_path": output_path,
                "error": str(exc),
            },
            indent=2,
            default=str,
        )


def create_blendspace(
    asset_path,
    skeleton_path,
    samples=None,
    animation_paths=None,
    sample_layout="speed_line",
    axis_x=None,
    axis_y=None,
    save=True,
):
    """Create and configure a BlendSpace through the validated native bridge."""
    import unreal

    samples = list(samples or [])
    animation_paths = [str(path) for path in list(animation_paths or []) if str(path)]
    axis_x = dict(axis_x or {"name": "Speed", "min": 0.0, "max": 150.0, "grid_num": 4})
    axis_y = dict(axis_y or {"name": "Direction", "min": -180.0, "max": 180.0, "grid_num": 4})
    generated_samples = False
    if not samples and animation_paths:
        if sample_layout != "speed_line":
            return json.dumps(
                {
                    "ok": False,
                    "status": "unsupported_sample_layout",
                    "sample_layout": sample_layout,
                    "supported": ["speed_line"],
                },
                indent=2,
            )
        minimum = float(axis_x.get("min", 0.0))
        maximum = float(axis_x.get("max", 150.0))
        interval = (maximum - minimum) / max(1, len(animation_paths) - 1)
        samples = [
            {
                "animation_path": path,
                "position": [
                    minimum + interval * index if len(animation_paths) > 1 else minimum,
                    0.0,
                    0.0,
                ],
            }
            for index, path in enumerate(animation_paths)
        ]
        generated_samples = True
    normalized = str(asset_path or "").split(".", 1)[0]
    package_path, _, asset_name = normalized.rpartition("/")
    if not package_path or not asset_name:
        return json.dumps({"ok": False, "status": "invalid_asset_path", "asset_path": asset_path}, indent=2)
    skeleton = unreal.EditorAssetLibrary.load_asset(str(skeleton_path))
    if not skeleton:
        return json.dumps({"ok": False, "status": "skeleton_not_found", "skeleton_path": skeleton_path}, indent=2)
    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    configure = getattr(bridge, "configure_blend_space", None) if bridge else None
    if not callable(configure):
        return json.dumps(
            {
                "ok": False,
                "status": "blendspace_sample_bridge_unavailable",
                "asset_path": normalized,
                "required_python_call": (
                    "unreal.AIStudioBridgeLibrary.configure_blend_space("
                    "blend_space, samples_json, axis_x_json, axis_y_json, save)"
                ),
                "acquisition_required": True,
                "evidence": {
                    "python_api": "No reflected UE 5.8 BlendSpace sample-authoring method was found.",
                    "cpp_api": (
                        "UBlendSpace::AddSample, ValidateSampleData, GetBlendSamples, "
                        "and IsValidBlendSampleIndex"
                    ),
                },
            },
            indent=2,
        )
    asset = unreal.EditorAssetLibrary.load_asset(normalized)
    created = False
    factory_cls = getattr(unreal, "BlendSpaceFactoryNew", None)
    blendspace_cls = getattr(unreal, "BlendSpace", None)
    if not factory_cls or not blendspace_cls:
        return json.dumps(
            {
                "ok": False,
                "status": "blendspace_factory_api_unavailable",
                "asset_path": normalized,
                "missing": [name for name, value in (("BlendSpaceFactoryNew", factory_cls), ("BlendSpace", blendspace_cls)) if not value],
            },
            indent=2,
        )
    if not asset:
        factory = factory_cls()
        try:
            factory.set_editor_property("target_skeleton", skeleton)
        except Exception:
            try:
                factory.set_editor_property("skeleton", skeleton)
            except Exception:
                pass
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name,
            package_path,
            blendspace_cls,
            factory,
        )
        created = asset is not None
    if not asset:
        return json.dumps(
            {"ok": False, "status": "create_asset_failed", "asset_path": normalized},
            indent=2,
        )
    try:
        response = configure(
            asset,
            json.dumps(samples),
            json.dumps(axis_x),
            json.dumps(axis_y),
            bool(save),
        )
        result = json.loads(response) if isinstance(response, str) else dict(response or {})
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "status": "blendspace_bridge_call_failed",
                "asset_path": normalized,
                "created": created,
                "error": str(exc),
            },
            indent=2,
        )
    result.update(
        {
            "asset_path": normalized,
            "skeleton_path": str(skeleton_path),
            "axis_x": axis_x,
            "axis_y": axis_y,
            "samples_requested": samples,
            "animation_paths": animation_paths,
            "sample_layout": sample_layout,
            "samples_generated_from_animation_paths": generated_samples,
            "created": created,
            "sample_authoring_status": (
                "validated_readback"
                if result.get("ok")
                and int(result.get("sample_count") or 0) >= len(samples)
                else "readback_failed"
            ),
        }
    )
    return json.dumps(result, indent=2, default=str)
