"""Selected animation FBX -> Maya animator controls -> clean engine FBX."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def transfer_fbx_to_engine(
    *,
    animation_fbx: str | Path,
    rig_scene: str | Path,
    target_hik_fbx: str | Path,
    output_scene: str | Path,
    output_fbx: str | Path,
    source_hik_fbx: str | Path | None = None,
    source_mapping: dict[str, dict[str, Any]] | None = None,
    source_tpose_frame: float | None = None,
    mapping_profile: str | Path | None = None,
    target_character: str | None = None,
    overwrite: bool = False,
    force_discard_scene: bool = False,
) -> dict[str, Any]:
    """Retarget, bake animator controls, then export only target deform joints.

    All inputs and both user-facing outputs are preflighted before Maya changes
    scenes. The companion/slot checks and clean-FBX reopen audit are delegated
    to their validated stages; no source or rig file is overwritten.
    """
    from maya_tools.Rigging.mocap.fbx_to_control_rig import (
        transfer_fbx_animation_to_control_rig,
    )
    from maya_tools.Animation.anim_export.clean_skeleton_export import (
        export_control_rig_skeleton,
    )

    inputs = [Path(value).expanduser().resolve() for value in
              (animation_fbx, rig_scene, target_hik_fbx)]
    if source_hik_fbx is not None:
        inputs.append(Path(source_hik_fbx).expanduser().resolve())
    if mapping_profile is not None:
        inputs.append(Path(mapping_profile).expanduser().resolve())
    scene = Path(output_scene).expanduser().resolve()
    engine = Path(output_fbx).expanduser().resolve()
    if engine.suffix.lower() != ".fbx":
        raise ValueError("output_fbx must end in .fbx")
    solved = scene.with_name(scene.stem + ".solved.fbx")
    if engine in inputs or engine in {scene, solved} or scene in inputs:
        raise ValueError("Output paths must not alias selected inputs or each other")
    if engine.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {engine}")

    transfer = transfer_fbx_animation_to_control_rig(
        animation_fbx=animation_fbx,
        rig_scene=rig_scene,
        target_hik_fbx=target_hik_fbx,
        output_scene=output_scene,
        source_hik_fbx=source_hik_fbx,
        source_mapping=source_mapping,
        source_tpose_frame=source_tpose_frame,
        mapping_profile=mapping_profile,
        target_character=target_character,
        overwrite=overwrite,
        force_discard_scene=force_discard_scene,
    )
    start, end = transfer["frame_range"]
    export = export_control_rig_skeleton(
        scene_path=scene,
        output_fbx=engine,
        start_frame=int(start),
        end_frame=int(end),
        overwrite=overwrite,
    )
    if not export.get("ok"):
        raise RuntimeError("Clean engine FBX export did not pass its reopen audit")
    return {
        "ok": True,
        "fbx_path": str(engine),
        "maya_scene": str(scene),
        "frame_range": transfer["frame_range"],
        "source_characterization": transfer["source_characterization"],
        "transfer": transfer,
        "clean_export": export,
    }
