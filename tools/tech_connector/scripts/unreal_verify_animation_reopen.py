"""Independently reopen a saved AnimSequence in a fresh Unreal process.

The launcher supplies TC_UNREAL_REOPEN_CONFIG_JSON. This script only reads
assets; a successful import process alone is not proof of on-disk persistence.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path


def _sample_motion(unreal, animation, bone: str, frames: int) -> dict:
    sampled_frames = sorted({0, (frames - 1) // 4, (frames - 1) // 2,
                             3 * (frames - 1) // 4, frames - 1})
    poses = [unreal.AnimationLibrary.get_bone_pose_for_frame(animation, bone, frame, False)
             for frame in sampled_frames]
    origin = poses[0]
    start_position = origin.translation
    start_rotation = origin.rotation
    position_deltas = []
    rotation_deltas = []
    for pose in poses[1:]:
        position = pose.translation
        position_deltas.append(math.sqrt(sum(
            (float(getattr(position, axis)) - float(getattr(start_position, axis))) ** 2
            for axis in ("x", "y", "z")
        )))
        rotation = pose.rotation
        dot = sum(float(getattr(rotation, axis)) * float(getattr(start_rotation, axis))
                  for axis in ("x", "y", "z", "w"))
        norm = math.sqrt(sum(float(getattr(rotation, axis)) ** 2
                             for axis in ("x", "y", "z", "w")))
        start_norm = math.sqrt(sum(float(getattr(start_rotation, axis)) ** 2
                                   for axis in ("x", "y", "z", "w")))
        if norm <= 0 or start_norm <= 0:
            raise RuntimeError(f"Invalid sampled rotation for {bone}")
        rotation_deltas.append(math.degrees(2 * math.acos(
            min(1.0, abs(dot / (norm * start_norm)))
        )))
    return {
        "bone": bone,
        "sampled_frames": sampled_frames,
        "maximum_translation_delta": max(position_deltas, default=0.0),
        "maximum_rotation_delta_degrees": max(rotation_deltas, default=0.0),
    }


def main() -> None:
    import unreal

    config = json.loads(os.environ["TC_UNREAL_REOPEN_CONFIG_JSON"])
    report = Path(config["report_json"])
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite reopen proof: {report}")
    animation = unreal.load_asset(config["anim_sequence"])
    skeleton = unreal.load_asset(config["skeleton_asset_path"])
    if not isinstance(animation, unreal.AnimSequence):
        raise TypeError("Saved asset did not reopen as an AnimSequence")
    if not isinstance(skeleton, unreal.Skeleton):
        raise TypeError("Requested Skeleton did not reopen")
    if animation.get_editor_property("skeleton") != skeleton:
        raise RuntimeError("Reopened animation has a different Skeleton")
    tracks = {str(name) for name in unreal.AnimationLibrary.get_animation_track_names(animation)}
    frames = int(unreal.AnimationLibrary.get_num_frames(animation))
    required = set(config["required_bones"])
    if (len(tracks) < config["minimum_track_count"]
            or frames < config["minimum_frame_count"]
            or not required.issubset(tracks)):
        raise RuntimeError("Reopened animation failed track/frame/bone gate")
    motion_bones = list(dict.fromkeys(config.get("motion_bones") or ()))
    if not set(motion_bones).issubset(tracks):
        raise RuntimeError("Reopened animation is missing a required moving bone")
    minimum_translation = float(config.get("minimum_motion_translation", 0.1))
    minimum_rotation = float(config.get("minimum_motion_rotation_degrees", 1.0))
    motion_samples = [_sample_motion(unreal, animation, bone, frames)
                      for bone in motion_bones]
    for sample in motion_samples:
        if (sample["maximum_translation_delta"] < minimum_translation
                and sample["maximum_rotation_delta_degrees"] < minimum_rotation):
            raise RuntimeError(f"Reopened animation has no required motion on {sample['bone']}")
    proof = {
        "ok": True,
        "anim_sequence": animation.get_path_name(),
        "skeleton": skeleton.get_path_name(),
        "track_count": len(tracks),
        "frame_count": frames,
        "play_length_seconds": float(animation.get_play_length()),
        "required_bones_present": sorted(required),
        "motion_samples": motion_samples,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("TC_UNREAL_REOPEN_PROOF=" + json.dumps(proof))


main()
