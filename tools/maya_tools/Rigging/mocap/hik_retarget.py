"""Data-driven HumanIK FBX retargeting for an authored Maya target rig."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maya import cmds, mel


def _source_scripts() -> None:
    for script in (
        "hikGlobalUtils.mel",
        "hikCharacterControlsUI.mel",
        "hikDefinitionOperations.mel",
        "hikInputSourceUtils.mel",
        "hikBakeOperation.mel",
    ):
        mel.eval(f'source "{script}";')


def _import_fbx(path: Path, namespace: str | None = None) -> None:
    if namespace:
        if not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        cmds.namespace(set=namespace)
    try:
        mel.eval("FBXResetImport;")
        # The default merge mode can silently reuse the target skeleton when
        # source and target share joint names. Retargeting requires two distinct
        # hierarchies, including when the source is the target's sister FBX.
        mel.eval("FBXImportMode -v add;")
        mel.eval('FBXImport -f "{}";'.format(str(path).replace("\\", "/")))
    finally:
        cmds.namespace(set=":")


def _source_joint(bone_name: str, imported_joints: set[str]) -> str:
    matches = [
        joint
        for joint in imported_joints
        if joint.split("|")[-1].split(":")[-1] == bone_name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one source joint named {bone_name}, found {matches}")
    return matches[0]


def _character_slots(character: str) -> dict[str, str]:
    """Read the imported HIK definition, retaining only unambiguous joint links."""
    from maya_tools.Rigging.mocap.setup_hik import DEFAULT_JOINT_MAP

    slots = {}
    for label in DEFAULT_JOINT_MAP:
        if not cmds.objExists(f"{character}.{label}"):
            continue
        matches = cmds.listConnections(
            f"{character}.{label}", source=True, destination=False, type="joint"
        ) or []
        if len(matches) == 1:
            slots[label] = matches[0]
    return slots


def _imported_character(before: set[str], imported_joints: set[str], role: str) -> tuple[str, dict[str, str]]:
    from maya_tools.Rigging.mocap.hik_mapping import REQUIRED_BODY_SLOTS

    candidates = []
    for character in set(cmds.ls(type="HIKCharacterNode") or []) - before:
        slots = _character_slots(character)
        hips = slots.get("Hips")
        if hips and (cmds.ls(hips, long=True) or [hips])[0] in imported_joints:
            candidates.append((character, slots))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one imported {role} HIK characterization with Hips on its "
            f"imported skeleton, found {[name for name, _ in candidates]}"
        )
    character, slots = candidates[0]
    if not bool(mel.eval(f'hikIsDefinitionLocked("{character}")')):
        raise RuntimeError(f"Imported {role} HumanIK definition is not locked: {character}")
    required = REQUIRED_BODY_SLOTS if role == "target" else REQUIRED_BODY_SLOTS - {"Reference"}
    missing = sorted(required - set(slots))
    if missing:
        raise RuntimeError(f"Imported {role} HumanIK definition lacks required slots: {missing}")
    return character, slots


def _character_joint(character: str, attribute: str) -> str:
    matches = cmds.listConnections(
        f"{character}.{attribute}", source=True, destination=False, type="joint"
    ) or []
    if len(matches) != 1:
        raise RuntimeError(f"Expected one joint on {character}.{attribute}, found {matches}")
    return matches[0]


def _position(node: str, frame: float) -> list[float]:
    cmds.currentTime(frame, edit=True)
    return [round(value, 5) for value in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def _bare(node: str) -> str:
    return str(node).split("|")[-1].split(":")[-1]


def _copy_matching_animation(
    animated_joints: set[str], characterized_joints: set[str], slots: dict[str, str]
) -> dict[str, Any]:
    """Apply a clip to its separately characterized sister skeleton.

    Match the full joint-parent lineage, not only the leaf name. Real face rigs
    can repeat a leaf joint name in separate branches; those names are not
    ambiguous when their ancestry is distinct. Every HIK slot must retain its
    lineage, so an unrelated skeleton cannot pass by sharing a few names.
    """
    lineage_cache: dict[str, tuple[str, ...]] = {}

    def lineage(joint: str) -> tuple[str, ...]:
        if joint in lineage_cache:
            return lineage_cache[joint]
        parents = cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or []
        if len(parents) > 1:
            raise RuntimeError(f"Ambiguous joint parent for {joint!r}")
        result = (*lineage(parents[0]), _bare(joint)) if parents else (_bare(joint),)
        lineage_cache[joint] = result
        return result

    def unique(joints: set[str], role: str) -> dict[tuple[str, ...], str]:
        result = {}
        for joint in joints:
            key = lineage(joint)
            if key in result:
                raise RuntimeError(f"Ambiguous {role} joint lineage {key!r}")
            result[key] = joint
        return result

    clip = unique(animated_joints, "animation")
    companion = unique(characterized_joints, "companion")
    missing = sorted(label for label, joint in slots.items() if lineage(joint) not in clip)
    if missing:
        raise RuntimeError(f"Animation FBX does not match companion HIK slots: {missing}")
    copied = 0
    for key, animated in clip.items():
        characterized = companion.get(key)
        if not characterized or not (cmds.keyframe(animated, query=True, keyframeCount=True) or 0):
            continue
        cmds.copyKey(animated)
        cmds.pasteKey(characterized, option="replaceCompletely")
        copied += 1
    if not copied:
        raise RuntimeError("Animation FBX has no joint keys to copy to the companion HIK rig")
    return {"matched_hik_slots": len(slots), "copied_joint_count": copied}


def retarget_fbx_hik(
    target_rig: str,
    source_fbx: str,
    output_fbx: str,
    source_mapping: dict[str, dict[str, Any]] | None = None,
    target_character: str | None = "Character1",
    source_character: str = "AIStudioSourceCharacter",
    source_namespace: str = "AIStudioSource",
    target_namespace: str = "MannyRig_v01_retarget",
    reset_scene: bool = True,
    source_tpose_frame: float | None = None,
    source_hik_fbx: str | None = None,
) -> dict[str, Any]:
    """Retarget from an imported HIK character or an explicit slot/bone map.

    An animation-only FBX can use ``source_hik_fbx`` when it has the same
    skeleton as a separately characterized sister FBX. Otherwise a mapped,
    uncharacterized FBX needs ``source_tpose_frame`` so locking the
    definition records a deliberate reference pose rather than an arbitrary
    animation frame. Already-characterized FBX files retain their authored
    HumanIK stance and do not need an external map.
    """

    target_path = Path(target_rig).resolve()
    source_path = Path(source_fbx).resolve()
    output_path = Path(output_fbx).resolve()
    companion_path = Path(source_hik_fbx).resolve() if source_hik_fbx else None
    for path in (target_path, source_path, companion_path):
        if path is None:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if reset_scene:
        cmds.file(new=True, force=True)
    cmds.loadPlugin("fbxmaya", quiet=True)
    target_before = set(cmds.ls(type="HIKCharacterNode") or [])
    _import_fbx(target_path)
    _source_scripts()
    target_imported = set(cmds.ls(type="joint", long=True) or [])
    if target_character is None:
        target_character, target_slots = _imported_character(
            target_before, target_imported, "target"
        )
    else:
        if not cmds.objExists(target_character):
            raise RuntimeError(f"Target HumanIK character does not exist: {target_character}")
        if not bool(mel.eval(f'hikIsDefinitionLocked("{target_character}")')):
            raise RuntimeError(f"Target HumanIK definition is not locked: {target_character}")
        target_slots = _character_slots(target_character)

    # FBX files commonly embed the generic character name "Character1". Maya's
    # FBX importer can delete the existing node when a second FBX uses it, even
    # when the current namespace differs. Give the selected target a unique
    # scene-local name before importing the animation source.
    target_character = cmds.rename(
        target_character, f"{target_namespace}_TargetHIK"
    )

    source_before = set(cmds.ls(type="HIKCharacterNode") or [])
    joints_before = set(cmds.ls(type="joint", long=True) or [])
    curves_before = set(cmds.ls(type="animCurve") or [])
    _import_fbx(source_path, source_namespace)
    imported_joints = set(cmds.ls(type="joint", long=True) or []) - joints_before
    imported_curves = set(cmds.ls(type="animCurve") or []) - curves_before
    if not imported_joints:
        raise RuntimeError("Source FBX imported no new joints")
    imported_characters = set(cmds.ls(type="HIKCharacterNode") or []) - source_before
    companion_transfer = None
    if imported_characters:
        source_character, mapped = _imported_character(
            source_before, imported_joints, "source"
        )
        characterization = "embedded"
    elif companion_path is not None:
        companion_before = set(cmds.ls(type="HIKCharacterNode") or [])
        companion_joints_before = set(cmds.ls(type="joint", long=True) or [])
        _import_fbx(companion_path, source_namespace + "HIK")
        companion_joints = (
            set(cmds.ls(type="joint", long=True) or []) - companion_joints_before
        )
        source_character, mapped = _imported_character(
            companion_before, companion_joints, "source"
        )
        companion_transfer = _copy_matching_animation(
            imported_joints, companion_joints, mapped
        )
        characterization = "companion_hik"
    else:
        if not source_mapping:
            raise ValueError("Source FBX has no HIK definition; source_mapping is required")
        if source_tpose_frame is None:
            raise ValueError(
                "Uncharacterized source FBX needs source_tpose_frame to record its HIK stance"
            )
        cmds.currentTime(source_tpose_frame, edit=True)
        mel.eval(f'hikCreateCharacter("{source_character}")')
        mapped = {}
        for label, item in source_mapping.items():
            slot = int(item["slot"])
            joint = _source_joint(str(item["bone"]), imported_joints)
            mel.eval(f'setCharacterObject "{joint}" "{source_character}" {slot} 0;')
            mapped[str(label)] = joint
        mel.eval(f'hikCharacterLock("{source_character}", 1, 1);')
        if not bool(mel.eval(f'hikIsDefinitionLocked("{source_character}")')):
            raise RuntimeError("Source HumanIK definition did not lock")
        characterization = "explicit_mapping"

    hips_label = "Hips"
    if hips_label not in mapped:
        raise ValueError("Source HumanIK definition must include Hips")
    # Confirm Maya can evaluate the recorded stance, then return to animation.
    mel.eval(f'hikSetCurrentCharacter("{source_character}")')
    mel.eval(f'hikSetStanceInput("{source_character}")')
    cmds.dgdirty(allPlugs=True)
    stance_frame = (
        source_tpose_frame if source_tpose_frame is not None
        else cmds.currentTime(query=True)
    )
    stance_hips = _position(mapped[hips_label], stance_frame)
    mel.eval(f'hikSetInactiveStanceInput("{source_character}")')
    cmds.dgdirty(allPlugs=True)
    keyed_joints = companion_joints if companion_transfer else imported_joints
    key_times = []
    for joint in keyed_joints:
        key_times.extend(cmds.keyframe(joint, query=True, timeChange=True) or [])
    if not key_times:
        for curve in imported_curves:
            key_times.extend(cmds.keyframe(curve, query=True, timeChange=True) or [])
    if not key_times:
        raise RuntimeError("Source FBX contains no animation keys")
    start, end = min(key_times), max(key_times)
    if source_tpose_frame is not None and not start <= source_tpose_frame <= end:
        raise ValueError(
            f"source_tpose_frame {source_tpose_frame} is outside animation range {start}–{end}"
        )
    cmds.playbackOptions(min=start, max=end, animationStartTime=start, animationEndTime=end)

    target_hips = _character_joint(target_character, "Hips")
    target_reference = _character_joint(target_character, "Reference")
    mel.eval(f'hikSetCurrentCharacter("{target_character}")')
    mel.eval(f'hikSetCharacterInput("{target_character}", "{source_character}")')
    cmds.dgdirty(allPlugs=True)
    sample_frames = [start, (start + end) / 2.0, end]
    pre_bake = [_position(target_hips, frame) for frame in sample_frames]
    if len({tuple(value) for value in pre_bake}) < 2:
        raise RuntimeError("Target hips did not respond to the HumanIK source")

    target_joints = [target_reference] + (
        cmds.listRelatives(target_reference, allDescendents=True, type="joint") or []
    )
    target_joints = list(dict.fromkeys(target_joints))
    cmds.bakeResults(
        target_joints,
        time=(start, end),
        simulation=True,
        sampleBy=1,
        disableImplicitControl=True,
        preserveOutsideKeys=True,
        sparseAnimCurveBake=False,
        minimizeRotation=True,
        controlPoints=False,
        shape=False,
    )
    post_bake = [_position(target_hips, frame) for frame in sample_frames]
    cmds.select(target_reference, hierarchy=True, replace=True)
    mel.eval("FBXResetExport;")
    mel.eval("FBXExportBakeComplexAnimation -v true;")
    mel.eval(f"FBXExportBakeComplexStart -v {start};")
    mel.eval(f"FBXExportBakeComplexEnd -v {end};")
    mel.eval("FBXExportBakeComplexStep -v 1;")
    # Keep the locked target characterization and its recorded stance. The
    # downstream control-transfer audit uses it to prove both Manny skeletons
    # agree before animation is applied.
    mel.eval("FBXExportSkeletonDefinitions -v true;")
    mel.eval("FBXExportInputConnections -v false;")
    mel.eval('FBXExportUpAxis "y";')
    mel.eval('FBXExport -f "{}" -s;'.format(str(output_path).replace("\\", "/")))
    return {
        "ok": output_path.is_file() and output_path.stat().st_size > 0,
        "target_rig": str(target_path),
        "source_fbx": str(source_path),
        "output_fbx": str(output_path),
        "output_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "target_character": target_character,
        "source_character": source_character,
        "source_mapping": mapped,
        "source_characterization": characterization,
        "source_stance_hips": stance_hips,
        "source_tpose_frame": source_tpose_frame,
        "source_hik_fbx": str(companion_path) if companion_path else None,
        "companion_transfer": companion_transfer,
        "target_mapping": target_slots,
        "frame_range": [start, end],
        "target_reference": target_reference,
        "target_joint_count": len(target_joints),
        "exported_skeleton_definitions": True,
        "pre_bake_hips": pre_bake,
        "post_bake_hips": post_bake,
    }
