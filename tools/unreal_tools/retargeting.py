"""Data-driven IK Rig and retargeting primitives for Unreal Editor Python."""

from __future__ import annotations


def _load_asset(unreal, asset_path: str):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Asset does not exist: {asset_path}")
    return asset


def inspect_bone_hierarchy(skeletal_mesh_path: str, root_bone: str) -> dict:
    """Traverse a SkeletalMesh hierarchy from a caller-supplied root bone."""

    import unreal

    mesh = _load_asset(unreal, skeletal_mesh_path)
    if mesh.get_class().get_name() != "SkeletalMesh":
        raise TypeError(f"Expected SkeletalMesh, got {mesh.get_class().get_name()}")

    root = str(root_bone)
    if str(mesh.get_bone_parent(root)) not in ("", "None"):
        raise ValueError(f"Bone is not a hierarchy root: {root}")

    bones = []
    pending = [(root, None, 0)]
    visited = set()
    while pending:
        name, parent, depth = pending.pop(0)
        if name in visited:
            continue
        visited.add(name)
        children = [str(value) for value in mesh.get_bone_children(name)]
        bones.append({"name": name, "parent": parent, "depth": depth, "children": children})
        pending.extend((child, name, depth + 1) for child in children)

    skeleton = mesh.get_editor_property("skeleton")
    return {
        "ok": bool(bones),
        "skeletal_mesh": skeletal_mesh_path,
        "skeleton": skeleton.get_path_name().split(".")[0] if skeleton else "",
        "root_bone": root,
        "bone_count": len(bones),
        "bones": bones,
    }


def create_ik_rig(
    skeletal_mesh_path: str,
    destination_path: str,
    asset_name: str,
    retarget_root: str,
    chains: list[dict],
    replace_existing: bool = False,
    save: bool = True,
) -> dict:
    """Create an IK Rig from explicit bone-chain data and verify its readback."""

    import unreal

    mesh = _load_asset(unreal, skeletal_mesh_path)
    asset_path = destination_path.rstrip("/") + "/" + asset_name
    existing = unreal.EditorAssetLibrary.load_asset(asset_path)
    if existing and not replace_existing:
        raise ValueError(f"IK Rig already exists: {asset_path}")
    if existing:
        unreal.EditorAssetLibrary.delete_asset(asset_path)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    rig = asset_tools.create_asset(
        asset_name,
        destination_path.rstrip("/"),
        unreal.IKRigDefinition,
        unreal.IKRigDefinitionFactory(),
    )
    if not rig:
        raise RuntimeError(f"Unreal did not create IK Rig: {asset_path}")

    controller = unreal.IKRigController.get_controller(rig)
    if not controller.set_skeletal_mesh(mesh):
        raise RuntimeError(f"IK Rig rejected SkeletalMesh: {skeletal_mesh_path}")
    if not controller.set_retarget_root(str(retarget_root)):
        raise RuntimeError(f"IK Rig rejected retarget root: {retarget_root}")

    added = []
    for chain in chains:
        requested_name = str(chain["name"])
        actual_name = str(
            controller.add_retarget_chain(
                requested_name,
                str(chain["start_bone"]),
                str(chain["end_bone"]),
                str(chain.get("goal_name") or ""),
            )
        )
        if actual_name != requested_name:
            raise RuntimeError(
                f"Retarget chain name changed from {requested_name} to {actual_name}; "
                "the requested chain may already exist or be invalid."
            )
        added.append(actual_name)

    if save and not unreal.EditorAssetLibrary.save_loaded_asset(rig, False):
        raise RuntimeError(f"Failed to save IK Rig: {asset_path}")
    report = inspect_ik_rig(asset_path)
    report["created"] = True
    report["chains_added"] = added
    return report


def inspect_ik_rig(asset_path: str) -> dict:
    """Read back the preview mesh, retarget root, and chain endpoints."""

    import unreal

    rig = _load_asset(unreal, asset_path)
    if rig.get_class().get_name() != "IKRigDefinition":
        raise TypeError(f"Expected IKRigDefinition, got {rig.get_class().get_name()}")
    controller = unreal.IKRigController.get_controller(rig)
    mesh = controller.get_skeletal_mesh()
    chains = []
    for chain in controller.get_retarget_chains():
        name = str(chain.get_editor_property("chain_name"))
        chains.append(
            {
                "name": name,
                "start_bone": str(controller.get_retarget_chain_start_bone(name)),
                "end_bone": str(controller.get_retarget_chain_end_bone(name)),
                "goal_name": str(controller.get_retarget_chain_goal(name)),
            }
        )
    return {
        "ok": bool(mesh) and bool(chains) and bool(str(controller.get_retarget_root())),
        "asset_path": asset_path,
        "skeletal_mesh": mesh.get_path_name().split(".")[0] if mesh else "",
        "retarget_root": str(controller.get_retarget_root()),
        "chains": chains,
    }


def create_ik_retargeter_from_template(
    template_path: str,
    destination_path: str,
    asset_name: str,
    source_ik_rig_path: str,
    target_ik_rig_path: str,
    mapping_mode: str = "exact",
    replace_existing: bool = False,
    save: bool = True,
) -> dict:
    """Duplicate a project retargeter, rebuild UE 5.8 ops, and map named chains."""

    import unreal

    template = _load_asset(unreal, template_path)
    source_rig = _load_asset(unreal, source_ik_rig_path)
    target_rig = _load_asset(unreal, target_ik_rig_path)
    asset_path = destination_path.rstrip("/") + "/" + asset_name
    existing = unreal.EditorAssetLibrary.load_asset(asset_path)
    if existing and not replace_existing:
        raise ValueError(f"IK Retargeter already exists: {asset_path}")
    if existing and not unreal.EditorAssetLibrary.delete_asset(asset_path):
        raise RuntimeError(f"Failed to replace IK Retargeter: {asset_path}")
    retargeter = unreal.EditorAssetLibrary.duplicate_asset(template_path, asset_path)
    if not retargeter:
        raise RuntimeError(f"Failed to duplicate retargeter template: {template_path}")

    controller = unreal.IKRetargeterController.get_controller(retargeter)
    controller.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, source_rig)
    controller.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, target_rig)
    controller.remove_all_ops()
    controller.add_default_ops()
    controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.SOURCE, source_rig)
    controller.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.TARGET, target_rig)
    mode = {
        "exact": unreal.AutoMapChainType.EXACT,
        "fuzzy": unreal.AutoMapChainType.FUZZY,
        "clear": unreal.AutoMapChainType.CLEAR,
    }.get(str(mapping_mode).lower())
    if mode is None:
        raise ValueError(f"Unsupported mapping mode: {mapping_mode}")
    for index in range(controller.get_num_retarget_ops()):
        controller.run_op_initial_setup(index)
    controller.auto_map_chains(unreal.AutoMapChainType.CLEAR, True)
    controller.auto_map_chains(mode, True)

    if save and not unreal.EditorAssetLibrary.save_loaded_asset(retargeter, False):
        raise RuntimeError(f"Failed to save IK Retargeter: {asset_path}")
    report = inspect_ik_retargeter(asset_path)
    if str(mapping_mode).lower() == "exact":
        source_controller = unreal.IKRigController.get_controller(source_rig)
        source_names = {
            str(chain.get_editor_property("chain_name"))
            for chain in source_controller.get_retarget_chains()
        }
        expected = {
            row["target_chain"]: row["target_chain"] if row["target_chain"] in source_names else "None"
            for row in report["chain_mappings"]
        }
        mismatches = [
            {
                "target_chain": row["target_chain"],
                "expected_source_chain": expected[row["target_chain"]],
                "actual_source_chain": row["source_chain"],
            }
            for row in report["chain_mappings"]
            if row["source_chain"] != expected[row["target_chain"]]
        ]
        report["exact_mapping_mismatches"] = mismatches
        report["ok"] = report["ok"] and not mismatches
    report.update({"created": True, "template_path": template_path, "mapping_mode": mapping_mode})
    return report


def inspect_ik_retargeter(asset_path: str) -> dict:
    """Read back rigs, UE 5.8 operation stack, and effective chain mappings."""

    import unreal

    retargeter = _load_asset(unreal, asset_path)
    if retargeter.get_class().get_name() != "IKRetargeter":
        raise TypeError(f"Expected IKRetargeter, got {retargeter.get_class().get_name()}")
    controller = unreal.IKRetargeterController.get_controller(retargeter)
    source_rig = controller.get_ik_rig(unreal.RetargetSourceOrTarget.SOURCE)
    target_rig = controller.get_ik_rig(unreal.RetargetSourceOrTarget.TARGET)
    target_controller = unreal.IKRigController.get_controller(target_rig) if target_rig else None
    mappings = []
    if target_controller:
        for chain in target_controller.get_retarget_chains():
            target_name = str(chain.get_editor_property("chain_name"))
            mappings.append(
                {
                    "target_chain": target_name,
                    "source_chain": str(controller.get_source_chain(target_name)),
                }
            )
    operations = [
        {
            "index": index,
            "name": str(controller.get_op_name(index)),
            "enabled": bool(controller.get_retarget_op_enabled(index)),
            "controller_class": controller.get_op_controller(index).get_class().get_name(),
        }
        for index in range(controller.get_num_retarget_ops())
    ]
    mapped_count = sum(row["source_chain"] not in ("", "None") for row in mappings)
    return {
        "ok": bool(source_rig) and bool(target_rig) and bool(operations) and mapped_count > 0,
        "asset_path": asset_path,
        "source_ik_rig": source_rig.get_path_name().split(".")[0] if source_rig else "",
        "target_ik_rig": target_rig.get_path_name().split(".")[0] if target_rig else "",
        "operations": operations,
        "chain_mappings": mappings,
        "mapped_chain_count": mapped_count,
        "unmapped_target_chains": [
            row["target_chain"] for row in mappings if row["source_chain"] in ("", "None")
        ],
    }


def discover_matching_ik_retargeters(
    source_skeletal_mesh_path: str,
    target_skeletal_mesh_path: str,
) -> dict:
    """Find project retargeters whose rig meshes match both requested skeletons."""

    import unreal

    source_mesh = _load_asset(unreal, source_skeletal_mesh_path)
    target_mesh = _load_asset(unreal, target_skeletal_mesh_path)
    source_skeleton = source_mesh.get_editor_property("skeleton")
    target_skeleton = target_mesh.get_editor_property("skeleton")
    source_skeleton_path = source_skeleton.get_path_name().split(".")[0] if source_skeleton else ""
    target_skeleton_path = target_skeleton.get_path_name().split(".")[0] if target_skeleton else ""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    class_path = unreal.TopLevelAssetPath("/Script/IKRig", "IKRetargeter")
    candidates = []
    rejected = []
    for asset_data in registry.get_assets_by_class(class_path, True) or []:
        path = str(asset_data.package_name)
        try:
            retargeter = asset_data.get_asset()
            controller = unreal.IKRetargeterController.get_controller(retargeter)
            source_rig = controller.get_ik_rig(unreal.RetargetSourceOrTarget.SOURCE)
            target_rig = controller.get_ik_rig(unreal.RetargetSourceOrTarget.TARGET)
            source_rig_mesh = (
                unreal.IKRigController.get_controller(source_rig).get_skeletal_mesh()
                if source_rig
                else None
            )
            target_rig_mesh = (
                unreal.IKRigController.get_controller(target_rig).get_skeletal_mesh()
                if target_rig
                else None
            )
            source_rig_mesh_path = source_rig_mesh.get_path_name().split(".")[0] if source_rig_mesh else ""
            target_rig_mesh_path = target_rig_mesh.get_path_name().split(".")[0] if target_rig_mesh else ""
            source_rig_skeleton = source_rig_mesh.get_editor_property("skeleton") if source_rig_mesh else None
            target_rig_skeleton = target_rig_mesh.get_editor_property("skeleton") if target_rig_mesh else None
            source_match = bool(
                source_rig_skeleton
                and source_rig_skeleton.get_path_name().split(".")[0] == source_skeleton_path
            )
            target_match = bool(
                target_rig_skeleton
                and target_rig_skeleton.get_path_name().split(".")[0] == target_skeleton_path
            )
            row = {
                "retargeter": path,
                "source_ik_rig": source_rig.get_path_name().split(".")[0] if source_rig else "",
                "target_ik_rig": target_rig.get_path_name().split(".")[0] if target_rig else "",
                "source_rig_mesh": source_rig_mesh_path,
                "target_rig_mesh": target_rig_mesh_path,
                "source_skeleton_match": source_match,
                "target_skeleton_match": target_match,
                "exact_mesh_match": (
                    source_rig_mesh_path == source_skeletal_mesh_path
                    and target_rig_mesh_path == target_skeletal_mesh_path
                ),
            }
            if source_match and target_match:
                candidates.append(row)
            else:
                rejected.append(row)
        except Exception as exc:
            rejected.append({"retargeter": path, "error": str(exc)})
    candidates.sort(key=lambda row: (not row["exact_mesh_match"], row["retargeter"].lower()))
    return {
        "ok": bool(candidates),
        "source_skeletal_mesh": source_skeletal_mesh_path,
        "source_skeleton": source_skeleton_path,
        "target_skeletal_mesh": target_skeletal_mesh_path,
        "target_skeleton": target_skeleton_path,
        "candidates": candidates,
        "rejected": rejected,
    }


def retarget_animation_with_matching_project_asset(
    animation_path: str,
    source_skeletal_mesh_path: str,
    target_skeletal_mesh_path: str,
    destination_path: str,
    destination_suffix: str = "_Retargeted",
    save: bool = True,
) -> dict:
    """Bake through a strictly matching project IK Retargeter and verify output."""

    discovery = discover_matching_ik_retargeters(
        source_skeletal_mesh_path,
        target_skeletal_mesh_path,
    )
    attempts = []
    for candidate in discovery["candidates"]:
        try:
            result = retarget_animation(
                animation_path,
                source_skeletal_mesh_path,
                target_skeletal_mesh_path,
                candidate["retargeter"],
                destination_path,
                destination_suffix=destination_suffix,
                save=save,
            )
        except Exception as exc:
            result = {"ok": False, "errors": [str(exc)]}
        attempts.append({"retargeter": candidate["retargeter"], "result": result})
        if result.get("ok"):
            return {
                "ok": True,
                "route": "unreal_editor_ik_bake",
                "discovery": discovery,
                "selected_retargeter": candidate["retargeter"],
                "retarget": result,
                "attempts": attempts,
            }
    return {
        "ok": False,
        "route": "unreal_editor_ik_bake",
        "discovery": discovery,
        "selected_retargeter": "",
        "attempts": attempts,
        "errors": ["No matching project IK Retargeter produced a target-skeleton AnimSequence."],
    }


def retarget_animation(
    animation_path: str,
    source_skeletal_mesh_path: str,
    target_skeletal_mesh_path: str,
    retargeter_path: str,
    destination_path: str,
    destination_suffix: str = "_Retargeted",
    save: bool = True,
) -> dict:
    """Retarget one animation and verify its selected target Skeleton identity."""

    import unreal

    animation = _load_asset(unreal, animation_path)
    source_mesh = _load_asset(unreal, source_skeletal_mesh_path)
    target_mesh = _load_asset(unreal, target_skeletal_mesh_path)
    retargeter = _load_asset(unreal, retargeter_path)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_data = registry.get_asset_by_object_path(animation.get_path_name())
    created_data = list(
        unreal.IKRetargetBatchOperation.duplicate_and_retarget(
            [asset_data],
            source_mesh,
            target_mesh,
            retargeter,
            "",
            "",
            "",
            destination_suffix,
            destination_path,
            False,
            True,
            True,
        )
        or []
    )
    target_skeleton = target_mesh.get_editor_property("skeleton")
    target_skeleton_path = target_skeleton.get_path_name().split(".")[0]
    outputs = []
    for row in created_data:
        asset = row.get_asset()
        if not asset:
            continue
        skeleton = asset.get_editor_property("skeleton")
        output = {
            "asset_path": asset.get_path_name().split(".")[0],
            "class": asset.get_class().get_name(),
            "skeleton": skeleton.get_path_name().split(".")[0] if skeleton else "",
        }
        outputs.append(output)
        if save:
            unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    valid_outputs = [
        row for row in outputs
        if row["class"] == "AnimSequence" and row["skeleton"] == target_skeleton_path
    ]
    return {
        "ok": bool(valid_outputs),
        "source_animation": animation_path,
        "retargeter": retargeter_path,
        "target_skeletal_mesh": target_skeletal_mesh_path,
        "target_skeleton": target_skeleton_path,
        "outputs": outputs,
        "valid_outputs": valid_outputs,
    }
