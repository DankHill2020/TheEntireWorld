"""Reference-only Maya animation work scenes and control-rig baking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import math

from maya import cmds, mel
from maya.api import OpenMaya

from maya_tools.Rigging.mocap import hik_mapping
from maya_tools.Rigging.mocap.control_identity import is_animator_control_identity


def _leaf(node: str) -> str:
    return str(node).split("|")[-1]


def _bare(node: str) -> str:
    return _leaf(node).split(":")[-1]


def _import_fbx(path: Path, namespace: str) -> list[str]:
    before = set(cmds.ls(long=True) or [])
    if not cmds.namespace(exists=namespace):
        cmds.namespace(add=namespace)
    cmds.namespace(set=namespace)
    try:
        mel.eval("FBXResetImport;")
        try:
            mel.eval("FBXImportSetMayaFrameRate -v true;")
        except RuntimeError:
            pass
        mel.eval('FBXImport -f "{}";'.format(str(path).replace("\\", "/")))
    finally:
        cmds.namespace(set=":")
    return sorted(set(cmds.ls(long=True) or []).difference(before))


def reference_rig(rig_scene: str | Path, namespace: str) -> dict[str, Any]:
    path = Path(rig_scene).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    reference_node = cmds.file(
        str(path),
        reference=True,
        namespace=namespace,
        mergeNamespacesOnClash=False,
        options="v=0;",
        returnNewNodes=False,
    )
    references = cmds.file(query=True, reference=True) or []
    matching = [item for item in references if Path(item.split("{")[0]).resolve() == path]
    if not matching:
        raise RuntimeError(f"Maya did not retain the rig as a reference: {path}")
    nodes = cmds.referenceQuery(matching[0], nodes=True, dagPath=True) or []
    if not nodes or not all(cmds.referenceQuery(node, isNodeReferenced=True) for node in nodes[:20]):
        raise RuntimeError("Rig reference nodes are not marked as referenced")
    return {
        "rig_scene": str(path),
        "reference": matching[0],
        "reference_node": reference_node,
        "namespace": namespace,
        "node_count": len(nodes),
    }


def _source_joint_map(namespace: str) -> dict[str, str]:
    local_joints = [
        joint for joint in (cmds.ls(type="joint", long=True) or [])
        if not cmds.referenceQuery(joint, isNodeReferenced=True)
    ]
    preferred = [
        joint for joint in local_joints
        if _leaf(joint).startswith(f"{namespace}:")
    ] if namespace else []
    candidates = preferred or local_joints
    result = {}
    for joint in candidates:
        name = _bare(joint)
        if name in result:
            raise RuntimeError(f"Solved animation has ambiguous joint name: {name}")
        result[name] = joint
    if not result:
        raise RuntimeError("Solved animation import created no local joints")
    return result


def _driven_joint(control: str) -> str | None:
    constraints = cmds.listConnections(
        control, source=False, destination=True, type="parentConstraint"
    ) or []
    for constraint in constraints:
        targets = cmds.parentConstraint(constraint, query=True, targetList=True) or []
        if not any(_leaf(target) == _leaf(control) for target in targets):
            continue
        driven = cmds.listConnections(
            constraint, source=False, destination=True, type="joint"
        ) or []
        if not driven:
            # Older rigs may blend an IK joint's authored and constrained
            # channels through a pre-existing pairBlend node. Follow that
            # connection instead of treating the animator control as absent.
            for blend in set(cmds.listConnections(
                constraint, source=False, destination=True, type="pairBlend"
            ) or []):
                driven.extend(cmds.listConnections(
                    blend, source=False, destination=True, type="joint"
                ) or [])
        if driven:
            return driven[0]
    return None


def _driven_parent_constraint_offset(control: str, driven: str) -> dict[str, Any]:
    for constraint in cmds.listConnections(
        control, source=False, destination=True, type="parentConstraint"
    ) or []:
        driven_nodes = cmds.listConnections(
            constraint, source=False, destination=True, type="joint"
        ) or []
        if not any(_leaf(node) == _leaf(driven) for node in driven_nodes):
            continue
        targets = cmds.parentConstraint(constraint, query=True, targetList=True) or []
        for index, target in enumerate(targets):
            if _leaf(target) != _leaf(control):
                continue
            rotate = cmds.getAttr(
                f"{constraint}.target[{index}].targetOffsetRotate"
            )[0]
            translate = cmds.getAttr(
                f"{constraint}.target[{index}].targetOffsetTranslate"
            )[0]
            return {
                "constraint": constraint,
                "rotate": list(rotate),
                "translate": list(translate),
                "has_rotation_offset": any(abs(float(value)) > 1e-4 for value in rotate),
            }
    return {
        "constraint": "",
        "rotate": [0.0, 0.0, 0.0],
        "translate": [0.0, 0.0, 0.0],
        "has_rotation_offset": False,
    }


def _referenced_rig_transforms(rig_namespace: str) -> list[str]:
    prefix = f"{rig_namespace}:"
    return [
        node for node in (cmds.ls(type="transform", long=True) or [])
        if _leaf(node).startswith(prefix)
        and cmds.referenceQuery(node, isNodeReferenced=True)
    ]


def _referenced_rig_joint_map(rig_namespace: str) -> dict[str, str]:
    prefix = f"{rig_namespace}:"
    result = {}
    for joint in cmds.ls(type="joint", long=True) or []:
        if not _leaf(joint).startswith(prefix) or not cmds.referenceQuery(joint, isNodeReferenced=True):
            continue
        name = _bare(joint)
        if name not in result:
            result[name] = joint
    return result


def _is_animator_control(node: str) -> bool:
    """Accept named controls or explicitly marked controls, never internal IK nodes."""
    return is_animator_control_identity(node, cmds.listSets(object=node) or ())


def _world_pose(node: str, frame: float) -> dict[str, list[float]]:
    cmds.currentTime(frame, edit=True)
    return {
        "translation": cmds.xform(node, query=True, worldSpace=True, translation=True),
        "rotation": cmds.xform(node, query=True, worldSpace=True, rotation=True),
    }


def _vector_error(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))


def _angular_error(left: list[float], right: list[float]) -> float:
    deltas = [((float(a) - float(b) + 180.0) % 360.0) - 180.0 for a, b in zip(left, right)]
    return math.sqrt(sum(delta * delta for delta in deltas))


def _world_quaternion(node: str) -> OpenMaya.MQuaternion:
    world_matrix = OpenMaya.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    return OpenMaya.MTransformationMatrix(world_matrix).rotation(asQuaternion=True)


def _quaternion_error(
    left_rotation: OpenMaya.MQuaternion,
    right_rotation: OpenMaya.MQuaternion,
) -> float:
    dot = abs(
        left_rotation.x * right_rotation.x
        + left_rotation.y * right_rotation.y
        + left_rotation.z * right_rotation.z
        + left_rotation.w * right_rotation.w
    )
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))


def _world_rotation_error(left_node: str, right_node: str) -> float:
    return _quaternion_error(_world_quaternion(left_node), _world_quaternion(right_node))


def _world_rotation_offset(source_node: str, target_node: str) -> OpenMaya.MQuaternion:
    return _world_quaternion(source_node).inverse() * _world_quaternion(target_node)


def discover_create_rig_bindings(
    rig_namespace: str,
    solved_namespace: str,
    allowed_bones: set[str] | None = None,
) -> list[dict[str, str]]:
    """Discover controls by their joint-driving graph, including non-``_ctrl`` rigs."""

    source = _source_joint_map(solved_namespace)
    bindings = []
    for control in _referenced_rig_transforms(rig_namespace):
        if not _is_animator_control(control):
            continue
        driven = _driven_joint(control)
        if not driven:
            continue
        driven_name = _bare(driven)
        if driven_name.endswith("_driver"):
            continue
        if driven_name.endswith(("_ik_Tip", "_fk_Tip")):
            source_name = driven_name[:-7] + "_Tip"
        elif driven_name.endswith(("_fk", "_ik")):
            source_name = driven_name[:-3]
        else:
            source_name = driven_name
        if allowed_bones is not None and source_name not in allowed_bones:
            continue
        solved_joint = source.get(source_name)
        if solved_joint:
            bindings.append({
                "source_joint": solved_joint,
                "source_bone": source_name,
                "control": control,
                "driven_joint": driven,
            })
    by_bone = {}
    for item in bindings:
        current = by_bone.get(item["source_bone"])
        if current is None or _bare(item["control"]).endswith("_fk_ctrl"):
            by_bone[item["source_bone"]] = item
    return sorted(by_bone.values(), key=lambda item: item["source_bone"])


def _preflight_bake_controls(controls: list[str]) -> dict[str, Any]:
    conflicts = []
    channel_modes = {}
    for control in controls:
        incoming_constraints = []
        for constraint_type in (
            "parentConstraint", "pointConstraint", "orientConstraint", "scaleConstraint"
        ):
            incoming_constraints.extend(
                cmds.listConnections(
                    control, source=True, destination=False, type=constraint_type
                ) or []
            )
        key_count = int(cmds.keyframe(control, query=True, keyframeCount=True) or 0)
        locked = [
            attribute for attribute in (
                "translateX", "translateY", "translateZ",
                "rotateX", "rotateY", "rotateZ",
            )
            if cmds.getAttr(f"{control}.{attribute}", lock=True)
        ]
        locked_translations = [name for name in locked if name.startswith("translate")]
        locked_rotations = [name for name in locked if name.startswith("rotate")]
        rotation_only = len(locked_translations) == 3 and not locked_rotations
        channel_modes[control] = "rotate" if rotation_only else "translate_rotate"
        invalid_locks = locked_rotations or (
            locked_translations if len(locked_translations) not in (0, 3) else []
        )
        if incoming_constraints or key_count or invalid_locks:
            conflicts.append({
                "control": control,
                "incoming_constraints": sorted(set(incoming_constraints)),
                "existing_key_count": key_count,
                "locked_channels": locked,
            })
    if conflicts:
        raise RuntimeError(
            "Destination animator controls are already driven or locked: "
            + json.dumps(conflicts[:10])
        )
    return {"control_count": len(controls), "conflicts": [], "channel_modes": channel_modes}


def _select_fk_and_spine_targets(rig_namespace: str) -> dict[str, Any]:
    """Put known rig variants in a single-target pose-solve mode.

    Current create-rig limbs use ``ikFkBlend=0`` for FK. The older Juice rig
    connects ``IkFk`` directly to FK weights and therefore needs 1 instead.
    Its deform spine also blends an IK joint with a ribbon joint at equal
    weight; that blend can flip 180 degrees during a control bake. Selecting
    its IK target is a scene-local reference edit, not a change to the rig file.
    """
    fk_switches = []
    for switch in _referenced_rig_transforms(rig_namespace):
        if not _bare(switch).endswith("_switch_ctrl"):
            continue
        for attribute, value in (("ikFkBlend", 0.0), ("IkFk", 1.0)):
            plug = f"{switch}.{attribute}"
            if cmds.objExists(plug):
                if not cmds.getAttr(plug, settable=True):
                    raise RuntimeError(f"Cannot select FK on locked or driven switch: {plug}")
                cmds.setAttr(plug, value)
                fk_switches.append({"control": switch, "attribute": attribute, "value": value})
                break

    spine_overrides = []
    for bone, joint in _referenced_rig_joint_map(rig_namespace).items():
        if not bone.startswith("spine"):
            continue
        for constraint in set(cmds.listConnections(
            joint, source=True, destination=False, type="parentConstraint"
        ) or []):
            targets = cmds.parentConstraint(constraint, query=True, targetList=True) or []
            weights = cmds.parentConstraint(constraint, query=True, weightAliasList=True) or []
            if not any(_bare(target).endswith("_ik") for target in targets):
                continue
            for target, alias in zip(targets, weights):
                if not _bare(target).endswith("_ribbon"):
                    continue
                plug = f"{constraint}.{alias}"
                if not cmds.getAttr(plug, settable=True):
                    raise RuntimeError(f"Cannot select IK spine target on driven weight: {plug}")
                cmds.setAttr(plug, 0.0)
                spine_overrides.append({"bone": bone, "constraint": constraint, "weight": alias, "value": 0.0})
    return {"fk_switches": fk_switches, "spine_overrides": spine_overrides}


def _solve_offset_delta(columns: list[list[float]], delta: list[float]) -> list[float]:
    """Invert the measured world-position response to three offset channels."""
    rows = [[float(columns[col][row]) for col in range(3)] + [float(delta[row])]
            for row in range(3)]
    for pivot in range(3):
        selected = max(range(pivot, 3), key=lambda row: abs(rows[row][pivot]))
        if abs(rows[selected][pivot]) < 1e-8:
            raise RuntimeError("Ribbon constraint offset has a singular translation response")
        rows[pivot], rows[selected] = rows[selected], rows[pivot]
        scale = rows[pivot][pivot]
        rows[pivot] = [value / scale for value in rows[pivot]]
        for row in range(3):
            if row != pivot:
                factor = rows[row][pivot]
                rows[row] = [value - factor * other
                             for value, other in zip(rows[row], rows[pivot])]
    return [rows[row][3] for row in range(3)]


def _calibrate_single_ribbon_spines(
    bindings: list[dict[str, str]], rig_joints: dict[str, str],
    start: float, end: float,
) -> list[dict[str, Any]]:
    """Correct a static ribbon rest offset without changing animator keys.

    Legacy rigs may drive a mapped deform spine joint from one ribbon target
    whose authored rest position differs from the characterized FBX. Measure
    the constraint's own offset response in a *referenced animation scene* and
    retain the edit only if start/middle/end poses agree after calibration.
    """
    corrections = []
    for item in bindings:
        bone = item["source_bone"]
        if not bone.startswith("spine") or bone not in rig_joints:
            continue
        rig_joint = rig_joints[bone]
        source_joint = item["source_joint"]
        constraints = set(cmds.listConnections(
            rig_joint, source=True, destination=False, type="parentConstraint"
        ) or [])
        ribbon = []
        for constraint in constraints:
            targets = cmds.parentConstraint(constraint, query=True, targetList=True) or []
            if len(targets) == 1 and _bare(targets[0]).endswith("_ribbon"):
                ribbon.append(constraint)
        if not ribbon:
            continue
        if len(ribbon) != 1:
            raise RuntimeError(f"Ambiguous ribbon constraints on {bone}: {ribbon}")
        constraint = ribbon[0]
        plug = f"{constraint}.target[0].targetOffsetTranslate"
        if not cmds.getAttr(plug, settable=True):
            raise RuntimeError(f"Cannot calibrate driven ribbon offset: {plug}")
        cmds.currentTime(start, edit=True)
        source_t = cmds.xform(source_joint, query=True, worldSpace=True, translation=True)
        before_t = cmds.xform(rig_joint, query=True, worldSpace=True, translation=True)
        before_error = _vector_error(source_t, before_t)
        if before_error <= 0.5:
            continue
        if _world_rotation_error(source_joint, rig_joint) > 2.0:
            raise RuntimeError(f"Ribbon {bone} has a rotation mismatch, not a static rest offset")
        old_offset = list(cmds.getAttr(plug)[0])
        columns = []
        try:
            for axis in range(3):
                trial = old_offset.copy()
                trial[axis] += 1.0
                cmds.setAttr(plug, *trial, type="double3")
                measured = cmds.xform(rig_joint, query=True, worldSpace=True, translation=True)
                columns.append([a - b for a, b in zip(measured, before_t)])
            cmds.setAttr(plug, *old_offset, type="double3")
            delta = _solve_offset_delta(
                columns, [a - b for a, b in zip(source_t, before_t)]
            )
            new_offset = [value + change for value, change in zip(old_offset, delta)]
            cmds.setAttr(plug, *new_offset, type="double3")
            sample_errors = []
            for frame in (start, (start + end) / 2.0, end):
                cmds.currentTime(frame, edit=True)
                target_t = cmds.xform(source_joint, query=True, worldSpace=True, translation=True)
                actual_t = cmds.xform(rig_joint, query=True, worldSpace=True, translation=True)
                sample_errors.append(_vector_error(target_t, actual_t))
            if max(sample_errors) > 0.5:
                raise RuntimeError(
                    f"Ribbon {bone} does not have a stable rest offset: {sample_errors}"
                )
            corrections.append({
                "bone": bone, "constraint": constraint,
                "before_error": before_error,
                "after_sample_errors": sample_errors,
                "old_offset": old_offset, "new_offset": new_offset,
            })
        except Exception:
            cmds.setAttr(plug, *old_offset, type="double3")
            raise
    return corrections


def bake_solved_skeleton_to_create_rig_controls(
    rig_namespace: str,
    solved_namespace: str,
    *,
    mapping_profile: str | Path,
    start_frame: float | None = None,
    end_frame: float | None = None,
    sample_subdivisions: int = 4,
) -> dict[str, Any]:
    if int(sample_subdivisions) < 1:
        raise ValueError("sample_subdivisions must be at least 1")
    rig_modes = _select_fk_and_spine_targets(rig_namespace)

    source = _source_joint_map(solved_namespace)
    profile = hik_mapping.load_profile(str(Path(mapping_profile).expanduser().resolve()))
    reference_name = (profile.get("Reference") or {}).get("joint")
    source_root = source.get(str(reference_name or "").split(":")[-1])
    if not source_root:
        raise RuntimeError(f"Solved skeleton has no mapped Reference joint: {reference_name}")
    resolved_profile, mapping_report = hik_mapping.resolve_to_scene(profile, source_root)
    allowed_bones = {
        _bare(row["joint"])
        for row in resolved_profile.values()
        if (row or {}).get("joint")
    }
    required = {
        _bare(resolved_profile[slot]["joint"])
        for slot in hik_mapping.REQUIRED_BODY_SLOTS
        if (resolved_profile.get(slot) or {}).get("joint")
    }
    keyed_times = []
    for joint in source.values():
        keyed_times.extend(cmds.keyframe(joint, query=True, timeChange=True) or [])
    if not keyed_times:
        raise RuntimeError("Solved animation skeleton contains no animation keys")
    source_key_times = sorted(set(float(value) for value in keyed_times))
    start = min(source_key_times) if start_frame is None else float(start_frame)
    end = max(source_key_times) if end_frame is None else float(end_frame)
    source_key_times = [value for value in source_key_times if start <= value <= end]
    key_deltas = [
        right - left for left, right in zip(source_key_times[:-1], source_key_times[1:])
        if right - left > 1e-6
    ]
    sample_step = min(key_deltas) if key_deltas else 1.0
    bake_sample_step = sample_step / float(sample_subdivisions)
    bindings = discover_create_rig_bindings(
        rig_namespace,
        solved_namespace,
        allowed_bones=allowed_bones,
    )
    bound = {item["source_bone"] for item in bindings}
    missing = sorted(required.difference(bound))
    # Some rigs leave the reference/root joint unconnected to animator controls.
    # That is safe only when its deform pose already matches the solved source
    # throughout the take; never silently omit an animated required bone.
    rig_joints = _referenced_rig_joint_map(rig_namespace)
    static_required_bones = []
    unresolved = []
    for bone in missing:
        solved_joint, rig_joint = source.get(bone), rig_joints.get(bone)
        if not solved_joint or not rig_joint:
            unresolved.append(bone)
            continue
        samples = [start + (end - start) * index / 20.0 for index in range(21)]
        if all(
            _vector_error(_world_pose(solved_joint, frame)["translation"],
                          _world_pose(rig_joint, frame)["translation"]) <= 0.5
            and _world_rotation_error(solved_joint, rig_joint) <= 2.0
            for frame in samples
        ):
            static_required_bones.append(bone)
        else:
            unresolved.append(bone)
    if unresolved:
        raise RuntimeError("Control binding discovery missed required bones: " + ", ".join(unresolved))

    controls = [item["control"] for item in bindings]
    preflight = _preflight_bake_controls(controls)
    channel_modes = preflight["channel_modes"]
    pair_blends_before = set(cmds.ls(type="pairBlend", long=True) or [])
    constraints = []
    solve_targets = []
    solve_data = []
    direct_data = []
    identity_values = list(OpenMaya.MMatrix())
    # Use direct constraints for the default identity-offset setup. Only rig
    # controls whose driven joints have a real rest offset need matrix solving.
    for index, item in enumerate(bindings):
        control_matrix = OpenMaya.MMatrix(
            cmds.xform(item["control"], query=True, worldSpace=True, matrix=True)
        )
        driven_matrix = OpenMaya.MMatrix(
            cmds.xform(item["driven_joint"], query=True, worldSpace=True, matrix=True)
        )
        driven_offset = driven_matrix * control_matrix.inverse()
        if max(abs(value - expected) for value, expected in zip(list(driven_offset), identity_values)) <= 1e-6:
            direct_data.append(item)
            continue
        target = cmds.spaceLocator(name=f"aiStudioControlBakeTarget{index}#")[0]
        solve_targets.append(target)
        solve_data.append((item, target, driven_offset.inverse()))

    sample_count = int(math.floor((end - start) / bake_sample_step))
    sample_times = [start + index * bake_sample_step for index in range(sample_count + 1)]
    if not sample_times or abs(sample_times[-1] - end) > 1e-8:
        sample_times.append(end)
    for frame in sample_times:
        cmds.currentTime(frame, edit=True)
        for item, target, inverse_offset in solve_data:
            source_matrix = OpenMaya.MMatrix(
                cmds.xform(item["source_joint"], query=True, worldSpace=True, matrix=True)
            )
            desired_control = inverse_offset * source_matrix
            cmds.xform(target, worldSpace=True, matrix=list(desired_control))
            cmds.setKeyframe(
                target,
                attribute=("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ"),
                time=frame,
            )

    for item in direct_data:
        constraint = cmds.orientConstraint if channel_modes[item["control"]] == "rotate" else cmds.parentConstraint
        constraints.extend(constraint(item["source_joint"], item["control"], maintainOffset=False) or [])
    for item, target, _ in solve_data:
        constraint = cmds.orientConstraint if channel_modes[item["control"]] == "rotate" else cmds.parentConstraint
        constraints.extend(constraint(target, item["control"], maintainOffset=False) or [])
    cmds.bakeResults(
        controls,
        time=(start, end),
        simulation=True,
        sampleBy=bake_sample_step,
        disableImplicitControl=True,
        preserveOutsideKeys=False,
        sparseAnimCurveBake=False,
        minimizeRotation=True,
        controlPoints=False,
        shape=False,
    )
    if constraints:
        cmds.delete(constraints)
    # Maya's sampleBy sequence can omit a fractional range endpoint. After
    # removing constraints, write the solve-target matrices onto the actual
    # channels in hierarchy order so the endpoint cannot fall back to interpolation.
    endpoint_data = [(item, item["source_joint"]) for item in direct_data]
    endpoint_data.extend((item, target) for item, target, _ in solve_data)
    endpoint_data.sort(key=lambda row: row[0]["control"].count("|"))
    for boundary in (start, end):
        cmds.currentTime(boundary, edit=True)
        for item, target in endpoint_data:
            if channel_modes[item["control"]] == "rotate":
                target_rotation = cmds.xform(
                    target, query=True, worldSpace=True, rotation=True
                )
                cmds.xform(item["control"], worldSpace=True, rotation=target_rotation)
                attributes = ("rotateX", "rotateY", "rotateZ")
            else:
                target_matrix = cmds.xform(target, query=True, worldSpace=True, matrix=True)
                cmds.xform(item["control"], worldSpace=True, matrix=target_matrix)
                attributes = (
                    "translateX", "translateY", "translateZ",
                    "rotateX", "rotateY", "rotateZ",
                )
            cmds.setKeyframe(item["control"], attribute=attributes, time=boundary)
    if solve_targets:
        cmds.delete(solve_targets)
    undeleted_constraints = [node for node in constraints if cmds.objExists(node)]
    undeleted_targets = [node for node in solve_targets if cmds.objExists(node)]
    new_pair_blends = sorted(
        set(cmds.ls(type="pairBlend", long=True) or []).difference(pair_blends_before)
    )
    if undeleted_constraints or undeleted_targets or new_pair_blends:
        raise RuntimeError(
            "Temporary bake drivers were not cleanly removed: "
            + json.dumps({
                "constraints": undeleted_constraints,
                "solve_targets": undeleted_targets,
                "pair_blends": new_pair_blends,
            })
        )
    key_counts = {control: int(cmds.keyframe(control, query=True, keyframeCount=True) or 0) for control in controls}
    unkeyed = [control for control, count in key_counts.items() if count == 0]
    if unkeyed:
        raise RuntimeError("Baked controls have no keys: " + ", ".join(unkeyed[:10]))
    ribbon_calibrations = _calibrate_single_ribbon_spines(
        bindings, rig_joints, start, end
    )
    binding_by_bone = {item["source_bone"]: item for item in bindings}
    sample_frames = [start + (end - start) * index / 20.0 for index in range(21)]
    pose_checks = []
    for bone in sorted(bound):
        source_joint = source.get(bone)
        rig_joint = rig_joints.get(bone)
        if not source_joint or not rig_joint:
            raise RuntimeError(f"Pose verification cannot resolve {bone}")
        binding = binding_by_bone[bone]
        control = binding["control"]
        constraint_offset = _driven_parent_constraint_offset(
            control, binding["driven_joint"]
        )
        for frame in sample_frames:
            source_pose = _world_pose(source_joint, frame)
            rig_pose = _world_pose(rig_joint, frame)
            translation_error = _vector_error(source_pose["translation"], rig_pose["translation"])
            absolute_rotation_error = _world_rotation_error(source_joint, rig_joint)
            control_translation = cmds.xform(
                control, query=True, worldSpace=True, translation=True
            )
            control_translation_error = _vector_error(
                source_pose["translation"], control_translation
            )
            control_rotation_error = _world_rotation_error(source_joint, control)
            # Controls are implementation details. A control can match while an
            # offset constraint leaves the exported deform skeleton incorrect.
            rotation_error = absolute_rotation_error
            pose_checks.append({
                "bone": bone,
                "frame": frame,
                "translation_error": translation_error,
                "rotation_error": rotation_error,
                "absolute_rotation_error": absolute_rotation_error,
                "control_translation_error": control_translation_error,
                "control_rotation_error": control_rotation_error,
                "driven_constraint_offset": constraint_offset,
                "source_translation": source_pose["translation"],
                "rig_translation": rig_pose["translation"],
                "source_rotation": source_pose["rotation"],
                "rig_rotation": rig_pose["rotation"],
            })
    worst_translation = max(item["translation_error"] for item in pose_checks)
    worst_rotation = max(item["rotation_error"] for item in pose_checks)
    if worst_translation > 0.5 or worst_rotation > 2.0:
        worst_translation_check = max(pose_checks, key=lambda item: item["translation_error"])
        worst_rotation_check = max(pose_checks, key=lambda item: item["rotation_error"])
        top_translation_checks = sorted(
            pose_checks, key=lambda item: item["translation_error"], reverse=True
        )[:8]
        top_rotation_checks = sorted(
            pose_checks, key=lambda item: item["rotation_error"], reverse=True
        )[:8]
        raise RuntimeError(
            f"Control bake pose mismatch: translation={worst_translation:.4f}, "
            f"rotation={worst_rotation:.4f}; "
            f"translation_check={worst_translation_check}; "
            f"rotation_check={worst_rotation_check}; "
            f"top_translation_checks={top_translation_checks}; "
            f"top_rotation_checks={top_rotation_checks}"
        )
    return {
        "ok": True,
        "frame_range": [start, end],
        "source_sample_step": sample_step,
        "bake_sample_step": bake_sample_step,
        "sample_subdivisions": int(sample_subdivisions),
        "source_key_time_count": len(source_key_times),
        "validation_sample_count": len(sample_frames),
        "binding_count": len(bindings),
        "static_required_bones": static_required_bones,
        "direct_constraint_count": len(direct_data),
        "offset_solve_count": len(solve_data),
        "controls": controls,
        "key_counts": key_counts,
        "control_preflight": preflight,
        "rig_modes": rig_modes,
        "ribbon_calibrations": ribbon_calibrations,
        "mapping_profile": str(Path(mapping_profile).expanduser().resolve()),
        "mapping_validation": mapping_report,
        "pose_checks": pose_checks,
        "worst_translation_error": worst_translation,
        "worst_rotation_error": worst_rotation,
    }


def build_referenced_animation_scene(
    *,
    rig_scene: str | Path,
    solved_animation_fbx: str | Path,
    output_scene: str | Path,
    rig_namespace: str = "CharacterRig",
    solved_namespace: str = "RetargetSolved",
    rig_adapter: str = "create_rig",
    mapping_profile: str | Path | None = None,
    start_frame: float | None = None,
    end_frame: float | None = None,
) -> dict[str, Any]:
    rig_path = Path(rig_scene).expanduser().resolve()
    solved_path = Path(solved_animation_fbx).expanduser().resolve()
    output_path = Path(output_scene).expanduser().resolve()
    if not solved_path.is_file():
        raise FileNotFoundError(solved_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmds.file(new=True, force=True)
    cmds.loadPlugin("fbxmaya", quiet=True)
    # Import the solved target skeleton first. FBX may preserve embedded
    # namespaces, so the later rig reference must be the collision-safe step.
    imported = _import_fbx(solved_path, solved_namespace)
    source_joint_count = len(_source_joint_map(solved_namespace))
    reference = reference_rig(rig_path, rig_namespace)
    if rig_adapter != "create_rig":
        raise ValueError(f"Unsupported rig adapter: {rig_adapter}")
    if not mapping_profile:
        raise ValueError("mapping_profile is required for control-rig baking")
    bake = bake_solved_skeleton_to_create_rig_controls(
        rig_namespace,
        solved_namespace,
        mapping_profile=mapping_profile,
        start_frame=start_frame,
        end_frame=end_frame,
    )
    cmds.file(rename=str(output_path))
    file_type = "mayaAscii" if output_path.suffix.lower() == ".ma" else "mayaBinary"
    cmds.file(save=True, force=True, type=file_type)
    retained_references = cmds.file(query=True, reference=True) or []
    if not any(Path(item.split("{")[0]).resolve() == rig_path for item in retained_references):
        raise RuntimeError("Saved animation scene lost its character rig reference")
    return {
        "ok": output_path.is_file() and output_path.stat().st_size > 0,
        "output_scene": str(output_path),
        "output_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "rig_reference": reference,
        "solved_animation_fbx": str(solved_path),
        "imported_node_count": len(imported),
        "solved_joint_count": source_joint_count,
        "bake": bake,
    }


def publish_referenced_animation_source(
    *,
    work_scene: str | Path,
    published_rig_scene: str | Path,
    output_scene: str | Path,
) -> dict[str, Any]:
    """Publish a portable review scene and prove its rig reference and keys survive reload."""
    work_path = Path(work_scene).expanduser().resolve()
    rig_path = Path(published_rig_scene).expanduser().resolve()
    output_path = Path(output_scene).expanduser().resolve()
    if not work_path.is_file():
        raise FileNotFoundError(work_path)
    if not rig_path.is_file():
        raise FileNotFoundError(rig_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmds.file(str(work_path), open=True, force=True, prompt=False)
    references = cmds.file(query=True, reference=True) or []
    if len(references) != 1:
        raise RuntimeError(
            f"Expected exactly one animator-rig reference, found {len(references)}: {references}"
        )
    old_reference = references[0]
    reference_node = cmds.referenceQuery(old_reference, referenceNode=True)
    cmds.file(
        str(rig_path),
        loadReference=reference_node,
        options="v=0;",
    )
    relocated = cmds.file(query=True, reference=True) or []
    if not any(Path(item.split("{")[0]).resolve() == rig_path for item in relocated):
        raise RuntimeError(f"Failed to relocate animator-rig reference to {rig_path}")

    cmds.file(rename=str(output_path))
    file_type = "mayaAscii" if output_path.suffix.lower() == ".ma" else "mayaBinary"
    cmds.file(save=True, force=True, type=file_type)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Maya did not write the published source scene: {output_path}")

    cmds.file(new=True, force=True)
    cmds.file(str(output_path), open=True, force=True, prompt=False)
    reopened_references = cmds.file(query=True, reference=True) or []
    matching_references = [
        item
        for item in reopened_references
        if Path(item.split("{")[0]).resolve() == rig_path
    ]
    if len(matching_references) != 1:
        raise RuntimeError(
            "Published scene did not reopen with exactly one relocated animator-rig "
            f"reference: {reopened_references}"
        )

    animation_curves = cmds.ls(type="animCurve") or []
    keyed_curves = [curve for curve in animation_curves if (cmds.keyframe(curve, query=True, keyframeCount=True) or 0) > 0]
    key_count = sum(
        int(cmds.keyframe(curve, query=True, keyframeCount=True) or 0)
        for curve in keyed_curves
    )
    if not keyed_curves or key_count == 0:
        raise RuntimeError("Published scene reopened without animation keys")

    referenced_nodes = cmds.referenceQuery(
        matching_references[0], nodes=True, dagPath=True
    ) or []
    referenced_controls = [
        node
        for node in referenced_nodes
        if cmds.objExists(node) and cmds.nodeType(node) == "transform"
        and _is_animator_control(node)
    ]
    if not referenced_controls:
        raise RuntimeError("Published rig reference reopened without animator controls")

    return {
        "ok": True,
        "output_scene": str(output_path),
        "output_bytes": output_path.stat().st_size,
        "rig_reference": str(rig_path),
        "reference_node": cmds.referenceQuery(matching_references[0], referenceNode=True),
        "referenced_node_count": len(referenced_nodes),
        "referenced_control_count": len(referenced_controls),
        "animation_curve_count": len(keyed_curves),
        "animation_key_count": key_count,
        "frame_range": [
            float(cmds.playbackOptions(query=True, minTime=True)),
            float(cmds.playbackOptions(query=True, maxTime=True)),
        ],
    }
