"""Manual Maya Script Editor runner for the referenced animation bake test.

This module intentionally does not initialize maya.standalone. Import it from an
already-running Maya session and call ``run_build``, ``run_publish``, or
``run_all``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from maya import cmds, mel

from maya_tools.Rigging.mocap import hik_mapping
from maya_tools.Rigging.mocap import referenced_animation_scene as transfer
from maya_tools.Rigging.mocap.referenced_animation_scene import (
    build_referenced_animation_scene,
    publish_referenced_animation_source,
)


# Exact inputs used for the verified Manny review take. These are ordinary
# dictionaries so they are easy to duplicate or edit in Maya's Script Editor.
BUILD_ARGS = {
    "rig_scene": Path(
        r"C:\depot\Time_Fighters 5.8\ArtSource\AIStudio\Rigs"
        r"\SKM_Manny_NoGeo\Manny_CreateRig_From_Test_v3.mb"
    ),
    "solved_animation_fbx": Path(
        r"C:\depot\Time_Fighters 5.8\ArtSource\AIStudio\Animations\Retargeted"
        r"\SKM_Manny_NoGeo"
        r"\CMU_01_03_playground___climb_hang_swing_SKM_Manny_NoGeo_HIK.fbx"
    ),
    "mapping_profile": Path(r"C:\depot\ArtSource\Rigs\Test\Test.json"),
    "output_scene": Path(
        r"C:\depot\tools\.codex_tmp\CMU_01_03_Manny_ReferencedControls_v3.mb"
    ),
    "rig_namespace": "MannyCharacterRig",
    "solved_namespace": "RetargetSolved",
    "rig_adapter": "create_rig",
    "start_frame": None,
    "end_frame": None,
}

PUBLISH_ARGS = {
    "work_scene": BUILD_ARGS["output_scene"],
    "published_rig_scene": BUILD_ARGS["rig_scene"],
    "output_scene": Path(
        r"C:\depot\Time_Fighters 5.8\ArtSource\AIStudio\Animations\Source"
        r"\SKM_Manny_NoGeo\CMU_01_03_Manny_ReferencedControls_FK_REVIEW.mb"
    ),
}

REPORT_PATH = PUBLISH_ARGS["output_scene"].with_suffix(".validation.json")

_STAGE = {
    "bindings": [],
    "constraints": [],
    "pair_blends_before": set(),
}


def _require_discard_permission(force: bool) -> None:
    if cmds.file(query=True, modified=True) and not force:
        raise RuntimeError(
            "The current Maya scene has unsaved changes. Save it first or rerun "
            "with force=True to permit the test to replace the current scene."
        )


def _print_summary(label: str, result: dict[str, Any]) -> None:
    bake = result.get("bake") or {}
    summary = {
        "ok": result.get("ok"),
        "output_scene": result.get("output_scene"),
        "output_bytes": result.get("output_bytes"),
        "binding_count": bake.get("binding_count"),
        "worst_translation_error": bake.get("worst_translation_error"),
        "worst_rotation_error": bake.get("worst_rotation_error"),
        "referenced_control_count": result.get("referenced_control_count"),
        "animation_curve_count": result.get("animation_curve_count"),
        "animation_key_count": result.get("animation_key_count"),
        "frame_range": result.get("frame_range") or bake.get("frame_range"),
    }
    print(f"{label}=" + json.dumps(summary, indent=2, default=str))


def _print_stage(label: str, result: dict[str, Any]) -> dict[str, Any]:
    print(f"{label}=" + json.dumps(result, indent=2, default=str))
    return result


def _resolve_stage() -> tuple[dict[str, str], dict[str, str], set[str], list[dict[str, str]]]:
    source = transfer._source_joint_map(str(BUILD_ARGS["solved_namespace"]))
    rig = transfer._referenced_rig_joint_map(str(BUILD_ARGS["rig_namespace"]))
    if not rig:
        raise RuntimeError("The animator rig is not referenced. Run stage_reference_rig().")
    profile = hik_mapping.load_profile(str(BUILD_ARGS["mapping_profile"]))
    reference_name = (profile.get("Reference") or {}).get("joint")
    source_root = source.get(str(reference_name or "").split(":")[-1])
    if not source_root:
        raise RuntimeError(f"Solved skeleton has no mapped Reference joint: {reference_name}")
    resolved, report = hik_mapping.resolve_to_scene(profile, source_root)
    if report.get("missing_required") or report.get("unresolved"):
        raise RuntimeError("Mapping does not resolve: " + json.dumps(report))
    allowed = {
        transfer._bare(row["joint"])
        for row in resolved.values()
        if (row or {}).get("joint")
    }
    bindings = transfer.discover_create_rig_bindings(
        str(BUILD_ARGS["rig_namespace"]),
        str(BUILD_ARGS["solved_namespace"]),
        allowed_bones=allowed,
    )
    return source, rig, allowed, bindings


def _source_frame_range(source: dict[str, str]) -> tuple[float, float]:
    times = []
    for joint in source.values():
        times.extend(cmds.keyframe(joint, query=True, timeChange=True) or [])
    if not times:
        raise RuntimeError("Solved skeleton has no animation keys")
    return float(min(times)), float(max(times))


def stage_import_solved(*, force: bool = False) -> dict[str, Any]:
    """Stage 1: open a clean scene and import only the solved animation FBX."""
    _require_discard_permission(force)
    stage_remove_preview()
    cmds.file(new=True, force=True)
    cmds.loadPlugin("fbxmaya", quiet=True)
    imported = transfer._import_fbx(
        Path(BUILD_ARGS["solved_animation_fbx"]),
        str(BUILD_ARGS["solved_namespace"]),
    )
    source = transfer._source_joint_map(str(BUILD_ARGS["solved_namespace"]))
    characters = cmds.ls(type="HIKCharacterNode") or []
    start, end = _source_frame_range(source)
    cmds.playbackOptions(minTime=start, maxTime=end, animationStartTime=start, animationEndTime=end)
    cmds.currentTime(start, edit=True)
    return _print_stage("AI_STUDIO_STAGE_IMPORT", {
        "ok": True,
        "source_joint_count": len(source),
        "imported_node_count": len(imported),
        "frame_range": [start, end],
        "time_unit": cmds.currentUnit(query=True, time=True),
        "hik_characters": characters,
        "characterization_available": bool(characters),
    })


def _source_hik_character(character: str | None = None) -> str:
    candidates = [
        node for node in (cmds.ls(type="HIKCharacterNode") or [])
        if not cmds.referenceQuery(node, isNodeReferenced=True)
    ]
    if character:
        if character not in candidates:
            raise RuntimeError(f"Source HIK character {character!r} was not found: {candidates}")
        return character
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one non-referenced HIK characterization in the solved FBX, "
            f"found {candidates}. Regenerate the solved FBX with skeleton definitions enabled."
        )
    return candidates[0]


def _source_hik_scripts() -> None:
    for script in (
        "hikGlobalUtils.mel",
        "hikCharacterControlsUI.mel",
        "hikDefinitionOperations.mel",
        "hikInputSourceUtils.mel",
    ):
        mel.eval(f'source "{script}";')


def stage_hik_stance(*, character: str | None = None) -> dict[str, Any]:
    """Stage 1b: force the solved skeleton into its recorded HIK T-stance."""
    _source_hik_scripts()
    character_node = _source_hik_character(character)
    locked = bool(mel.eval(f'hikIsDefinitionLocked("{character_node}")'))
    if not locked:
        raise RuntimeError(f"HIK characterization is not locked: {character_node}")
    previous_input = str(mel.eval(f'hikGetCharacterInputString("{character_node}")'))
    mel.eval(f'hikSetCurrentCharacter("{character_node}")')
    mel.eval(f'hikSetStanceInput("{character_node}")')
    cmds.dgdirty(allPlugs=True)
    _STAGE["source_hik_character"] = character_node
    return _print_stage("AI_STUDIO_STAGE_HIK_STANCE", {
        "ok": True,
        "character": character_node,
        "locked": locked,
        "previous_input": previous_input,
        "current_input": str(mel.eval(f'hikGetCharacterInputString("{character_node}")')),
    })


def stage_hik_animation(*, character: str | None = None) -> dict[str, Any]:
    """Leave temporary stance input and restore the skeleton's baked animation."""
    _source_hik_scripts()
    character_node = _source_hik_character(character or _STAGE.get("source_hik_character"))
    mel.eval(f'hikSetInactiveStanceInput("{character_node}")')
    cmds.dgdirty(allPlugs=True)
    return _print_stage("AI_STUDIO_STAGE_HIK_ANIMATION", {
        "ok": True,
        "character": character_node,
        "current_input": str(mel.eval(f'hikGetCharacterInputString("{character_node}")')),
    })


def stage_reference_rig() -> dict[str, Any]:
    """Stage 2: reference the animator rig and resolve graph-derived bindings."""
    if not transfer._source_joint_map(str(BUILD_ARGS["solved_namespace"])):
        raise RuntimeError("Run stage_import_solved() first")
    reference = transfer.reference_rig(
        BUILD_ARGS["rig_scene"], str(BUILD_ARGS["rig_namespace"])
    )
    switches = []
    for node in transfer._referenced_rig_transforms(str(BUILD_ARGS["rig_namespace"])):
        if transfer._bare(node).endswith("_switch_ctrl") and cmds.objExists(node + ".ikFkBlend"):
            cmds.setAttr(node + ".ikFkBlend", 0.0)
            switches.append(node)
    _source, _rig, _allowed, bindings = _resolve_stage()
    _STAGE["bindings"] = bindings
    return _print_stage("AI_STUDIO_STAGE_REFERENCE", {
        "ok": True,
        "reference": reference,
        "binding_count": len(bindings),
        "fk_switches": switches,
    })


def stage_audit_retarget(*, sample_frames: list[float] | None = None) -> dict[str, Any]:
    """Stage 3: audit the solved skeleton before it is connected to controls."""
    source, rig, allowed, bindings = _resolve_stage()
    start, end = _source_frame_range(source)
    frames = sample_frames or [start, (start + end) / 2.0, end]
    hierarchy_mismatches = []
    animated_non_root_translations = []
    length_checks = []
    excluded_translation_bones = {"root", "pelvis"}
    for bone in sorted(allowed.intersection(source).intersection(rig)):
        source_parent = transfer._bare((cmds.listRelatives(source[bone], parent=True, type="joint", fullPath=True) or [""])[0])
        rig_parent = transfer._bare((cmds.listRelatives(rig[bone], parent=True, type="joint", fullPath=True) or [""])[0])
        if source_parent != rig_parent:
            hierarchy_mismatches.append({"bone": bone, "source_parent": source_parent, "rig_parent": rig_parent})
        translation_keys = sum(
            int(cmds.keyframe(source[bone] + ".translate" + axis, query=True, keyframeCount=True) or 0)
            for axis in "XYZ"
        )
        if bone not in excluded_translation_bones and translation_keys:
            animated_non_root_translations.append({"bone": bone, "key_count": translation_keys})
        for frame in frames:
            cmds.currentTime(frame, edit=True)
            source_translate = cmds.getAttr(source[bone] + ".translate")[0]
            rig_translate = cmds.getAttr(rig[bone] + ".translate")[0]
            source_length = math.sqrt(sum(float(value) ** 2 for value in source_translate))
            rig_length = math.sqrt(sum(float(value) ** 2 for value in rig_translate))
            if bone not in excluded_translation_bones:
                length_checks.append({
                    "bone": bone,
                    "frame": frame,
                    "source_length": source_length,
                    "rig_length": rig_length,
                    "error": abs(source_length - rig_length),
                })
    control_offsets = []
    for item in bindings:
        offset = transfer._driven_parent_constraint_offset(item["control"], item["driven_joint"])
        if offset["has_rotation_offset"] or any(abs(float(value)) > 1e-4 for value in offset["translate"]):
            control_offsets.append({"bone": item["source_bone"], "control": item["control"], **offset})
    worst_length_error = max((row["error"] for row in length_checks), default=0.0)
    result = {
        "ok": not hierarchy_mismatches and worst_length_error <= 0.1 and not animated_non_root_translations,
        "frame_range": [start, end],
        "sample_frames": frames,
        "hierarchy_mismatches": hierarchy_mismatches,
        "animated_non_root_translations": animated_non_root_translations,
        "control_constraint_offsets": control_offsets,
        "worst_bone_length_error": worst_length_error,
        "worst_length_checks": sorted(length_checks, key=lambda row: row["error"], reverse=True)[:10],
    }
    return _print_stage("AI_STUDIO_STAGE_RETARGET_AUDIT", result)


def stage_preview_transfer(*, maintain_offset: bool = False) -> dict[str, Any]:
    """Stage 4: connect solved joints to controls without baking, for scrubbing."""
    stage_remove_preview()
    _source, _rig, _allowed, bindings = _resolve_stage()
    controls = [item["control"] for item in bindings]
    transfer._preflight_bake_controls(controls)
    _STAGE["pair_blends_before"] = set(cmds.ls(type="pairBlend", long=True) or [])
    constraints = []
    for index, item in enumerate(bindings):
        constraints.extend(cmds.parentConstraint(
            item["source_joint"],
            item["control"],
            maintainOffset=maintain_offset,
            name=f"AIStudioTransferPreview_{index}",
        ) or [])
    _STAGE["bindings"] = bindings
    _STAGE["constraints"] = constraints
    return _print_stage("AI_STUDIO_STAGE_PREVIEW", {
        "ok": True,
        "maintain_offset": maintain_offset,
        "constraint_count": len(constraints),
        "inspect": "Scrub the timeline now. Run stage_validate_transfer() for deform-skeleton errors.",
    })


def stage_remove_preview() -> dict[str, Any]:
    """Remove only temporary preview constraints created by this runner."""
    candidates = list(_STAGE.get("constraints") or [])
    candidates.extend(cmds.ls("AIStudioTransferPreview_*", type="parentConstraint") or [])
    existing = sorted(set(node for node in candidates if cmds.objExists(node)))
    if existing:
        cmds.delete(existing)
    _STAGE["constraints"] = []
    return {"ok": True, "removed_constraint_count": len(existing)}


def stage_bake_preview() -> dict[str, Any]:
    """Stage 5: bake the currently previewed transfer and remove its constraints."""
    constraints = [node for node in (_STAGE.get("constraints") or []) if cmds.objExists(node)]
    bindings = list(_STAGE.get("bindings") or [])
    if not constraints or not bindings:
        raise RuntimeError("Run stage_preview_transfer() before stage_bake_preview()")
    source = transfer._source_joint_map(str(BUILD_ARGS["solved_namespace"]))
    start, end = _source_frame_range(source)
    controls = [item["control"] for item in bindings]
    cmds.bakeResults(
        controls,
        time=(start, end),
        simulation=True,
        sampleBy=1,
        disableImplicitControl=True,
        preserveOutsideKeys=False,
        sparseAnimCurveBake=False,
        minimizeRotation=True,
        controlPoints=False,
        shape=False,
    )
    cleanup = stage_remove_preview()
    new_pair_blends = sorted(
        set(cmds.ls(type="pairBlend", long=True) or []).difference(_STAGE.get("pair_blends_before") or set())
    )
    key_counts = {control: int(cmds.keyframe(control, query=True, keyframeCount=True) or 0) for control in controls}
    result = {
        "ok": not new_pair_blends and all(key_counts.values()),
        "frame_range": [start, end],
        "control_count": len(controls),
        "removed_constraint_count": cleanup["removed_constraint_count"],
        "new_pair_blends": new_pair_blends,
        "unkeyed_controls": [control for control, count in key_counts.items() if not count],
    }
    return _print_stage("AI_STUDIO_STAGE_BAKE", result)


def stage_validate_transfer(
    *,
    sample_frames: list[float] | None = None,
    translation_tolerance: float = 0.5,
    rotation_tolerance: float = 2.0,
) -> dict[str, Any]:
    """Stage 6: compare solved joints only with final driven deform joints."""
    source, rig, allowed, _bindings = _resolve_stage()
    start, end = _source_frame_range(source)
    frames = sample_frames or [start, (start + end) / 2.0, end]
    checks = []
    for frame in frames:
        cmds.currentTime(frame, edit=True)
        for bone in sorted(allowed.intersection(source).intersection(rig)):
            source_position = cmds.xform(source[bone], query=True, worldSpace=True, translation=True)
            rig_position = cmds.xform(rig[bone], query=True, worldSpace=True, translation=True)
            checks.append({
                "bone": bone,
                "frame": frame,
                "translation_error": transfer._vector_error(source_position, rig_position),
                "rotation_error": transfer._world_rotation_error(source[bone], rig[bone]),
            })
    worst_translation = max((row["translation_error"] for row in checks), default=float("inf"))
    worst_rotation = max((row["rotation_error"] for row in checks), default=float("inf"))
    result = {
        "ok": worst_translation <= translation_tolerance and worst_rotation <= rotation_tolerance,
        "worst_translation_error": worst_translation,
        "worst_rotation_error": worst_rotation,
        "worst_translation_checks": sorted(checks, key=lambda row: row["translation_error"], reverse=True)[:10],
        "worst_rotation_checks": sorted(checks, key=lambda row: row["rotation_error"], reverse=True)[:10],
    }
    return _print_stage("AI_STUDIO_STAGE_TRANSFER_VALIDATION", result)


def run_build(*, force: bool = False, **overrides: Any) -> dict[str, Any]:
    """Import solved FBX, reference the rig, bake controls, validate, and save."""
    _require_discard_permission(force)
    arguments = dict(BUILD_ARGS)
    arguments.update(overrides)
    result = build_referenced_animation_scene(**arguments)
    _print_summary("AI_STUDIO_MANUAL_BUILD", result)
    return result


def run_publish(*, force: bool = False, **overrides: Any) -> dict[str, Any]:
    """Publish the work scene and prove its reference and keys survive reopening."""
    _require_discard_permission(force)
    arguments = dict(PUBLISH_ARGS)
    arguments.update(overrides)
    result = publish_referenced_animation_source(**arguments)
    _print_summary("AI_STUDIO_MANUAL_PUBLISH", result)
    return result


def run_all(*, force: bool = False) -> dict[str, Any]:
    """Run the tested build and publish sequence, then save a combined report."""
    _require_discard_permission(force)
    build = run_build(force=True)
    publish = run_publish(force=True)
    report = {"ok": bool(build.get("ok") and publish.get("ok")), "build": build, "publish": publish}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("AI_STUDIO_MANUAL_REPORT=" + str(REPORT_PATH))
    return report
