"""Export only baked deform joints from a referenced Maya control-rig scene.

FBX's selected-only export follows rig input connections and can silently pull
driver/FK/IK joints into an engine asset. An isolated, constraint-baked joint
copy avoids that graph traversal. The copy is independently reimported before
the export is reported as valid.
"""

from __future__ import annotations

from pathlib import Path

from maya_tools.Animation.anim_export.bridge_export import export_fbx


def _joint_order(joints: dict[str, str], parent_of) -> list[str]:
    """Return parent-first order; reject partial or disconnected skeletons."""
    name_of = {node: name for name, node in joints.items()}
    if len(name_of) != len(joints):
        raise ValueError("Joint names must identify distinct scene nodes")
    roots = [name for name, node in joints.items() if parent_of(node) not in name_of]
    if len(roots) != 1:
        raise ValueError(f"Selected skeleton must have exactly one root, found {len(roots)}")
    pending = dict(joints)
    ordered: list[str] = []
    while pending:
        progressed = False
        for name, node in list(pending.items()):
            parent = parent_of(node)
            parent_name = name_of.get(parent)
            if parent_name in pending:
                continue
            if parent_name is None and parent is not None:
                # A top-level transform may own the skeleton root, but a
                # missing joint parent would leave an incomplete chain.
                import maya.cmds as cmds
                if cmds.nodeType(parent) == "joint":
                    raise ValueError(f"Selected skeleton omits parent of {name}: {parent}")
            ordered.append(name)
            del pending[name]
            progressed = True
        if not progressed:
            raise ValueError("Selected skeleton has a cyclic parent relationship")
    return ordered


def export_control_rig_skeleton(
    scene_path: str | Path,
    output_fbx: str | Path,
    *,
    start_frame: int,
    end_frame: int,
    rig_namespace: str = "CharacterRig",
    solved_namespace: str = "RetargetSolved",
    overwrite: bool = False,
) -> dict:
    """Open a baked-control scene, export its clean deform skeleton, reopen-audit it.

    The solved skeleton identifies the intended deform-joint subset, not the
    motion to export: the referenced control rig is sampled after any edits.
    Requires mayapy/Maya's Python environment.
    """
    source_path = Path(scene_path).expanduser().resolve()
    target_path = Path(output_fbx).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Control-rig scene does not exist: {source_path}")
    if target_path == source_path:
        raise ValueError("Output FBX cannot alias the control-rig scene")
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite FBX: {target_path}")
    start, end = int(start_frame), int(end_frame)
    if end < start:
        raise ValueError("End frame precedes start frame")

    import maya.cmds as cmds
    from maya_tools.Rigging.mocap import referenced_animation_scene as scene

    cmds.file(str(source_path), open=True, force=True, prompt=False)
    deform = scene._referenced_rig_joint_map(rig_namespace)
    solved = scene._source_joint_map(solved_namespace)
    joints = {name: node for name, node in deform.items() if name in solved}
    if "origin" not in joints or len(joints) < 20:
        raise RuntimeError("Scene lacks a complete solved/deform skeleton pair")
    def parent_of(node):
        return (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
    order = _joint_order(joints, parent_of)
    if order[0] != "origin":
        raise ValueError("The export skeleton must have origin as its root")
    namespace = "TechConnectorEngineExport"
    if cmds.namespace(exists=namespace):
        raise ValueError(f"Temporary export namespace already exists: {namespace}")
    cmds.namespace(add=namespace)
    clones: dict[str, str] = {}
    constraints: list[str] = []
    name_of = {node: name for name, node in joints.items()}
    try:
        for name in order:
            original = joints[name]
            clone = cmds.createNode("joint", name=f"{namespace}:{name}")
            parent_name = name_of.get(parent_of(original))
            if parent_name is not None:
                clone = cmds.parent(clone, clones[parent_name], relative=True)[0]
            for attr in ("rotateOrder", "segmentScaleCompensate"):
                cmds.setAttr(f"{clone}.{attr}", cmds.getAttr(f"{original}.{attr}"))
            for attr in ("jointOrient", "translate", "rotate", "scale"):
                cmds.setAttr(f"{clone}.{attr}", *cmds.getAttr(f"{original}.{attr}")[0], type="double3")
            clones[name] = clone
        constraints = [cmds.parentConstraint(joints[name], clones[name], maintainOffset=False)[0]
                       for name in order]
        cmds.bakeResults(list(clones.values()), simulation=True, time=(start, end),
                         sampleBy=1, preserveOutsideKeys=False, sparseAnimCurveBake=False,
                         attribute=["translate", "rotate"])
        cmds.delete(constraints)
        constraints = []
        sample_frames = [start + (end - start) * index / 20.0 for index in range(21)]
        baseline = {}
        worst_clone_translation = 0.0
        worst_clone_rotation = 0.0
        for frame in sample_frames:
            cmds.currentTime(frame, edit=True)
            baseline[frame] = {}
            for name in order:
                original, clone = joints[name], clones[name]
                original_t = cmds.xform(original, query=True, worldSpace=True, translation=True)
                clone_t = cmds.xform(clone, query=True, worldSpace=True, translation=True)
                original_q = scene._world_quaternion(original)
                clone_q = scene._world_quaternion(clone)
                worst_clone_translation = max(worst_clone_translation, scene._vector_error(original_t, clone_t))
                worst_clone_rotation = max(worst_clone_rotation, scene._quaternion_error(original_q, clone_q))
                baseline[frame][name] = (original_t, original_q)
        if worst_clone_translation > 0.001 or worst_clone_rotation > 0.1:
            raise RuntimeError("Clean skeleton bake does not match the control-rig deform pose")
        export_fbx(str(target_path), start_frame=start, end_frame=end,
                   nodes=[clones["origin"]])
    finally:
        if constraints:
            cmds.delete(constraints)
        if clones and cmds.objExists(clones.get("origin", "")):
            cmds.delete(clones["origin"])
        if cmds.namespace(exists=namespace):
            cmds.namespace(removeNamespace=namespace)

    cmds.file(new=True, force=True)
    scene._import_fbx(target_path, "EngineAudit")
    imported = scene._source_joint_map("EngineAudit")
    if set(imported) != set(joints):
        raise RuntimeError(
            f"FBX joint topology changed: {len(imported)} imported versus {len(joints)} exported; "
            f"missing={sorted(set(joints)-set(imported))[:10]}, "
            f"extra={sorted(set(imported)-set(joints))[:10]}"
        )
    worst_translation = 0.0
    worst_rotation = 0.0
    for frame in sample_frames:
        cmds.currentTime(frame, edit=True)
        for name in order:
            original_t, original_q = baseline[frame][name]
            node = imported[name]
            actual_t = cmds.xform(node, query=True, worldSpace=True, translation=True)
            worst_translation = max(worst_translation, scene._vector_error(original_t, actual_t))
            worst_rotation = max(worst_rotation, scene._quaternion_error(original_q, scene._world_quaternion(node)))
    if worst_translation > 0.001 or worst_rotation > 0.1:
        raise RuntimeError(
            f"FBX reimport pose mismatch: translation={worst_translation:.6f}, "
            f"rotation={worst_rotation:.6f}"
        )
    return {
        "ok": True,
        "source_scene": str(source_path),
        "output_fbx": str(target_path),
        "output_bytes": target_path.stat().st_size,
        "frame_range": [start, end],
        "joint_count": len(imported),
        "animation_curve_count": len(cmds.ls(type="animCurve") or []),
        "sample_frame_count": len(sample_frames),
        "worst_translation_error": worst_translation,
        "worst_rotation_error": worst_rotation,
        "unwanted_joint_count": 0,
    }
