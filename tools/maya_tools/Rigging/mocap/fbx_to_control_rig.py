"""End-to-end FBX -> HumanIK target skeleton -> Maya animator controls.

The companion HIK FBX is a characterized *skeleton*, while ``rig_scene`` is
the actual Maya control rig that remains referenced in the output scene.
Nothing is inferred from a file's name or a project's default character.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _input_file(value: str | Path, suffixes: set[str], role: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"{role} must be {', '.join(sorted(suffixes))}: {path}")
    return path


def transfer_fbx_animation_to_control_rig(
    *,
    animation_fbx: str | Path,
    rig_scene: str | Path,
    target_hik_fbx: str | Path,
    output_scene: str | Path,
    mapping_profile: str | Path | None = None,
    solved_fbx: str | Path | None = None,
    source_mapping: dict[str, dict[str, Any]] | None = None,
    source_hik_fbx: str | Path | None = None,
    source_tpose_frame: float | None = None,
    target_character: str | None = None,
    rig_namespace: str = "CharacterRig",
    solved_namespace: str = "RetargetSolved",
    overwrite: bool = False,
    force_discard_scene: bool = False,
) -> dict[str, Any]:
    """Transfer a selected animation FBX onto a selected Maya control rig.

    The animation FBX's embedded locked HIK character is preferred. An
    uncharacterized source uses a selected sister ``source_hik_fbx`` or,
    when omitted, tries the selected target's companion HIK skeleton. Their
    HIK slots and full joint lineages must match; unrelated skeletons fail
    closed. An explicit ``source_mapping`` instead needs a known T-pose frame.
    ``mapping_profile`` optionally overrides the target slot map. Otherwise
    the selected companion HIK FBX supplies a profile for the control bake.

    Both stages open clean Maya scenes. Save any current scene before calling.
    Outputs are refused when present unless ``overwrite`` is explicit.
    """
    from maya_tools.Rigging.mocap.hik_retarget import retarget_fbx_hik
    from maya_tools.Rigging.mocap.referenced_animation_scene import (
        build_referenced_animation_scene,
    )

    animation = _input_file(animation_fbx, {".fbx"}, "animation_fbx")
    rig = _input_file(rig_scene, {".ma", ".mb"}, "rig_scene")
    target = _input_file(target_hik_fbx, {".fbx"}, "target_hik_fbx")
    source_companion = (
        _input_file(source_hik_fbx, {".fbx"}, "source_hik_fbx")
        if source_hik_fbx is not None else None
    )
    if source_companion is None and source_mapping is None:
        source_companion = target
    profile = (
        _input_file(mapping_profile, {".json"}, "mapping_profile")
        if mapping_profile is not None else None
    )
    scene = Path(output_scene).expanduser().resolve()
    if scene.suffix.lower() not in {".ma", ".mb"}:
        raise ValueError("output_scene must end in .ma or .mb")
    solved = (
        Path(solved_fbx).expanduser().resolve()
        if solved_fbx is not None
        else scene.with_name(scene.stem + ".solved.fbx")
    )
    if solved.suffix.lower() != ".fbx":
        raise ValueError("solved_fbx must end in .fbx")
    inputs = {animation, rig, target}
    if source_companion is not None:
        inputs.add(source_companion)
    if profile is not None:
        inputs.add(profile)
    else:
        profile = scene.with_name(scene.stem + ".hik_mapping.json")
    if scene in inputs or solved in inputs or scene == solved:
        raise ValueError("Output paths must be distinct from inputs and each other")
    outputs = (solved, scene) if mapping_profile is not None else (solved, scene, profile)
    for output in outputs:
        if output.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    # Validate profile syntax before either stage replaces Maya's current scene.
    from maya_tools.Rigging.mocap.hik_mapping import load_profile

    if mapping_profile is not None:
        load_profile(str(profile))
    from maya import cmds

    if cmds.file(query=True, modified=True) and not force_discard_scene:
        raise RuntimeError(
            "Current Maya scene has unsaved changes; save it or pass "
            "force_discard_scene=True explicitly"
        )
    solved_report = retarget_fbx_hik(
        target_rig=str(target),
        source_fbx=str(animation),
        output_fbx=str(solved),
        source_mapping=source_mapping,
        source_hik_fbx=str(source_companion) if source_companion else None,
        source_tpose_frame=source_tpose_frame,
        target_character=target_character,
        source_character="AnimationSourceHIK",
        source_namespace="AnimationSource",
        target_namespace="SelectedTarget",
    )
    if not solved_report.get("ok"):
        raise RuntimeError("HumanIK retarget did not produce a solved FBX")
    if mapping_profile is None:
        from maya_tools.Rigging.mocap.setup_hik import DEFAULT_JOINT_MAP

        target_slots = solved_report["target_mapping"]
        generated = {
            label: {
                "index": int(row["index"]),
                "joint": str(target_slots.get(label) or "").split("|")[-1].split(":")[-1],
            }
            for label, row in DEFAULT_JOINT_MAP.items()
        }
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(json.dumps({"mapping": generated}, indent=2), encoding="utf-8")
    scene_report = build_referenced_animation_scene(
        rig_scene=str(rig),
        solved_animation_fbx=str(solved),
        output_scene=str(scene),
        rig_namespace=rig_namespace,
        solved_namespace=solved_namespace,
        mapping_profile=str(profile),
        start_frame=solved_report["frame_range"][0],
        end_frame=solved_report["frame_range"][1],
    )
    if not scene_report.get("ok"):
        raise RuntimeError("Control-rig bake did not produce a Maya scene")
    return {
        "ok": True,
        "animation_fbx": str(animation),
        "target_hik_fbx": str(target),
        "source_hik_fbx": str(source_companion) if source_companion else None,
        "rig_scene": str(rig),
        "mapping_profile": str(profile),
        "solved_fbx": str(solved),
        "output_scene": str(scene),
        "frame_range": solved_report["frame_range"],
        "source_characterization": solved_report["source_characterization"],
        "source_character": solved_report["source_character"],
        "target_character": solved_report["target_character"],
        "source_slots": solved_report["source_mapping"],
        "target_slots": solved_report["target_mapping"],
        "source_stance_hips": solved_report["source_stance_hips"],
        "hik_retarget": solved_report,
        "control_bake": scene_report,
    }


def transfer_fbx_animation_dialog(**kwargs: Any) -> dict[str, Any] | None:
    """Pick the source FBX, Maya rig, companion HIK FBX, and output scene.

    Cancellation leaves the scene unchanged. The dialog offers the selected
    target's companion HIK FBX or a separately selected characterized sister
    FBX for the animation skeleton. An embedded HIK definition takes priority.
    Explicit ``source_mapping`` and ``source_tpose_frame`` can be passed in
    ``kwargs`` for an uncharacterized source without a companion FBX.
    """
    from maya import cmds

    prompts = (
        ("animation_fbx", "Select animation FBX", 1, "FBX (*.fbx)"),
        ("rig_scene", "Select Maya control rig", 1, "Maya scene (*.ma *.mb)"),
        ("target_hik_fbx", "Select companion HIK skeleton FBX", 1, "FBX (*.fbx)"),
        ("output_scene", "Save baked control-rig scene", 0, "Maya scene (*.ma *.mb)"),
    )
    selected = {}
    for key, caption, file_mode, file_filter in prompts:
        if (key == "output_scene" and kwargs.get("source_hik_fbx") is None
                and kwargs.get("source_mapping") is None):
            choice = cmds.confirmDialog(
                title="Animation source characterization",
                message=(
                    "If the animation FBX is not already characterized, which "
                    "HumanIK skeleton matches its joint hierarchy?"
                ),
                button=["Use target HIK FBX", "Select source HIK FBX", "Cancel"],
                defaultButton="Use target HIK FBX",
                cancelButton="Cancel",
                dismissString="Cancel",
            )
            if choice == "Cancel":
                return None
            if choice == "Select source HIK FBX":
                source_paths = cmds.fileDialog2(
                    caption="Select animation's characterized sister FBX",
                    fileMode=1, fileFilter="FBX (*.fbx)",
                )
                if not source_paths:
                    return None
                kwargs["source_hik_fbx"] = source_paths[0]
            elif choice != "Use target HIK FBX":
                return None
        paths = cmds.fileDialog2(
            caption=caption, fileMode=file_mode, fileFilter=file_filter
        )
        if not paths:
            return None
        selected[key] = paths[0]
    if kwargs.get("source_hik_fbx") is None and kwargs.get("source_mapping") is None:
        # The common animation-only export uses the same skeleton as the
        # selected rig's characterized companion. The retargeter verifies
        # every HIK slot and parent relationship before copying any keys.
        kwargs["source_hik_fbx"] = selected["target_hik_fbx"]
    return transfer_fbx_animation_to_control_rig(**selected, **kwargs)
