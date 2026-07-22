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
        mel.eval('FBXImport -f "{}";'.format(str(path).replace("\\", "/")))
    finally:
        cmds.namespace(set=":")


def _source_joint(namespace: str, bone_name: str, excluded_namespace: str) -> str:
    matches = [
        joint
        for joint in (cmds.ls(type="joint", long=True) or [])
        if joint.split("|")[-1].split(":")[-1] == bone_name
        and f"{excluded_namespace}:" not in joint
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one source joint named {bone_name}, found {matches}")
    return matches[0]


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


def retarget_fbx_hik(
    target_rig: str,
    source_fbx: str,
    output_fbx: str,
    source_mapping: dict[str, dict[str, Any]],
    target_character: str = "Character1",
    source_character: str = "AIStudioSourceCharacter",
    source_namespace: str = "AIStudioSource",
    target_namespace: str = "MannyRig_v01_retarget",
    reset_scene: bool = True,
) -> dict[str, Any]:
    """Retarget from an explicit ``{label: {slot, bone}}`` HumanIK map."""

    target_path = Path(target_rig).resolve()
    source_path = Path(source_fbx).resolve()
    output_path = Path(output_fbx).resolve()
    for path in (target_path, source_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not source_mapping:
        raise ValueError("source_mapping is required; HumanIK slots are never guessed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if reset_scene:
        cmds.file(new=True, force=True)
    cmds.loadPlugin("fbxmaya", quiet=True)
    _import_fbx(target_path)
    _source_scripts()
    if not cmds.objExists(target_character):
        raise RuntimeError(f"Target HumanIK character does not exist: {target_character}")
    if not bool(mel.eval(f'hikIsDefinitionLocked("{target_character}")')):
        raise RuntimeError(f"Target HumanIK definition is not locked: {target_character}")

    _import_fbx(source_path, source_namespace)
    mel.eval(f'hikCreateCharacter("{source_character}")')
    mapped = {}
    for label, item in source_mapping.items():
        slot = int(item["slot"])
        joint = _source_joint(source_namespace, str(item["bone"]), target_namespace)
        mel.eval(f'setCharacterObject "{joint}" "{source_character}" {slot} 0;')
        mapped[str(label)] = joint
    mel.eval(f'hikCharacterLock("{source_character}", 1, 1);')
    if not bool(mel.eval(f'hikIsDefinitionLocked("{source_character}")')):
        raise RuntimeError("Source HumanIK definition did not lock")

    hips_label = "Hips"
    if hips_label not in mapped:
        raise ValueError("source_mapping must define the Hips slot")
    key_times = cmds.keyframe(mapped[hips_label], query=True, timeChange=True) or []
    if not key_times:
        key_times = cmds.keyframe(query=True, timeChange=True) or []
    if not key_times:
        raise RuntimeError("Source FBX contains no animation keys")
    start, end = min(key_times), max(key_times)
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
        "frame_range": [start, end],
        "target_reference": target_reference,
        "target_joint_count": len(target_joints),
        "exported_skeleton_definitions": True,
        "pre_bake_hips": pre_bake,
        "post_bake_hips": post_bake,
    }
