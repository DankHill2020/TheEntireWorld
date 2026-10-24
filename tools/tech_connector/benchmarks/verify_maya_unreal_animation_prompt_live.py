"""Verify a saved prompt-bound Maya-control-FBX to Unreal AnimSequence receipt."""

from __future__ import annotations

import json
import math
from pathlib import Path

from tech_connector.scripts.run_prompt_maya_unreal_animation_proof import (
    PROOF_SCHEMA, _sha256, _unreal_asset_file, compile_proof_plan,
)


def _path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Missing proof path")
    return Path(value).expanduser().resolve()


def _within(value: object, limit: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and 0 <= number <= limit


def verify_maya_unreal_animation_prompt_proof(report_path: str | Path) -> dict:
    """Bind the custom prompt, selected inputs, host reports, and saved outputs."""
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schema") != PROOF_SCHEMA or report.get("ok") is not True:
        raise ValueError("Not a successful Maya-to-Unreal animation proof")
    prompt = report.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Proof has no custom prompt")
    plan, maya_params, unreal_params = compile_proof_plan(prompt)
    if report.get("compiled_operations") != [stage["operation"] for stage in plan["stages"]]:
        raise ValueError("Compiled operations changed")
    selected = report.get("selected_inputs") or {}
    input_hashes = report.get("input_sha256") or {}
    expected_inputs = {
        role: _path(maya_params[role])
        for role in ("animation_fbx", "rig_scene", "target_hik_fbx", "source_hik_fbx")
        if maya_params.get(role)
    }
    expected_inputs["project"] = _path(report.get("project"))
    if set(selected) != set(expected_inputs) or set(input_hashes) != set(expected_inputs):
        raise ValueError("Selected input roles are incomplete or unexpected")
    for role, expected in expected_inputs.items():
        if _path(selected[role]) != expected or not expected.is_file() or _sha256(expected) != input_hashes[role]:
            raise ValueError(f"Selected {role} is missing or changed")

    maya = report.get("maya") or {}
    unreal = report.get("unreal") or {}
    if not isinstance(maya, dict) or not isinstance(unreal, dict) or not maya.get("ok") or not unreal.get("ok"):
        raise ValueError("Host reports are incomplete")
    scene = _path(maya_params["output_scene"])
    fbx = _path(maya_params["output_fbx"])
    if (_path(maya.get("animation_fbx")) != expected_inputs["animation_fbx"]
            or _path(maya.get("maya_scene")) != scene
            or _path(maya.get("fbx_path")) != fbx
            or _path(unreal.get("animation_fbx")) != fbx):
        raise ValueError("Maya/Unreal artifact handoff does not match the prompt")
    reopen = unreal.get("independent_reopen") or {}
    if reopen.get("ok") is not True:
        raise ValueError("Unreal fresh-process reopen did not pass")
    animation = str(unreal.get("anim_sequence") or "")
    skeleton = str(unreal.get("skeleton") or "").split(".", 1)[0]
    if (not animation.startswith(str(unreal_params["destination_path"]).rstrip("/") + "/")
            or skeleton != str(unreal_params["skeleton_path"]).split(".", 1)[0]
            or reopen.get("anim_sequence") != animation
            or str(reopen.get("skeleton") or "").split(".", 1)[0] != skeleton
            or int(unreal.get("track_count") or 0) < 1
            or int(unreal.get("frame_count") or 0) < 2
            or reopen.get("track_count") != unreal.get("track_count")
            or reopen.get("frame_count") != unreal.get("frame_count")):
        raise ValueError("Unreal asset readback does not match the selected Skeleton or prompt")
    gate = report.get("motion_gate")
    if gate is not None and not isinstance(gate, dict):
        raise ValueError("Motion gate is malformed")
    gate = gate or {}
    try:
        translation_limit = float(gate.get("minimum_translation", 0.1))
        rotation_limit = float(gate.get("minimum_rotation_degrees", 1.0))
    except (TypeError, ValueError):
        raise ValueError("Motion gate thresholds are malformed") from None
    if (not math.isfinite(translation_limit) or translation_limit <= 0
            or not math.isfinite(rotation_limit) or rotation_limit <= 0):
        raise ValueError("Motion gate thresholds must be positive and finite")
    samples = reopen.get("motion_samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("Unreal fresh-process readback did not prove bone motion")
    sampled_bones = []
    for row in samples:
        if not isinstance(row, dict) or not isinstance(row.get("bone"), str) or not row["bone"]:
            raise ValueError("Motion sample has no bone identity")
        frames = row.get("sampled_frames")
        if (not isinstance(frames, list)
                or any(type(frame) is not int or frame < 0 or frame >= int(unreal["frame_count"])
                       for frame in frames)
                or len(set(frames)) < 2):
            raise ValueError("Motion sample does not span valid animation frames")
        if (not _within(row.get("maximum_translation_delta"), float("inf"))
                or not _within(row.get("maximum_rotation_delta_degrees"), float("inf"))
                or (float(row["maximum_translation_delta"]) < translation_limit
                    and float(row["maximum_rotation_delta_degrees"]) < rotation_limit)):
            raise ValueError("Motion sample does not prove nontrivial bone motion")
        sampled_bones.append(row["bone"])
    if len(set(sampled_bones)) != len(sampled_bones):
        raise ValueError("Duplicate motion samples cannot prove distinct bones")
    expected_bones = gate.get("moving_bones")
    if expected_bones is not None and (
        not isinstance(expected_bones, list) or not expected_bones
        or any(not isinstance(bone, str) or not bone for bone in expected_bones)
        or set(sampled_bones) != set(expected_bones)
        or len(expected_bones) != len(set(expected_bones))
    ):
        raise ValueError("Motion samples do not match the requested gate")
    asset = _unreal_asset_file(expected_inputs["project"], animation).resolve()
    audit = maya.get("reopen_audit") or {}
    clean = maya.get("clean_export") or {}
    if (int(audit.get("rig_reference_count") or 0) != 1
            or int(audit.get("keyed_control_count") or 0) < 1
            or int(audit.get("mapped_bone_count") or 0) < 17
            or int(audit.get("sample_frame_count") or 0) < 21
            or not _within(audit.get("worst_translation_error"), 0.5)
            or not _within(audit.get("worst_rotation_error"), 2.0)
            or clean.get("ok") is not True
            or int(clean.get("joint_count") or 0) < 17
            or int(clean.get("unwanted_joint_count", -1)) != 0
            or int(clean.get("sample_frame_count") or 0) < 21
            or not _within(clean.get("worst_translation_error"), 0.5)
            or not _within(clean.get("worst_rotation_error"), 2.0)):
        raise ValueError("Maya scene or clean FBX audit is outside tolerance")

    expected_outputs = {
        "maya_scene": scene, "fbx_path": fbx, "unreal_asset": asset,
        "maya_report": Path(report_path).resolve().with_name(Path(report_path).stem + ".maya.json"),
        "unreal_report": Path(report_path).resolve().with_name(Path(report_path).stem + ".unreal.json"),
    }
    output_files = report.get("output_files") or {}
    output_bytes = report.get("output_bytes") or {}
    output_hashes = report.get("output_sha256") or {}
    if not (set(output_files) == set(output_bytes) == set(output_hashes) == set(expected_outputs)):
        raise ValueError("Output artifact roles are incomplete or unexpected")
    for role, expected in expected_outputs.items():
        if (_path(output_files[role]) != expected or not expected.is_file()
                or expected.stat().st_size != output_bytes[role]
                or _sha256(expected) != output_hashes[role]):
            raise ValueError(f"Saved {role} is missing or changed")
    if json.loads(expected_outputs["maya_report"].read_text(encoding="utf-8")) != maya:
        raise ValueError("Maya host report does not match receipt")
    if json.loads(expected_outputs["unreal_report"].read_text(encoding="utf-8")) != unreal:
        raise ValueError("Unreal host report does not match receipt")
    return {
        "verified": True,
        "animation_fbx": str(expected_inputs["animation_fbx"]),
        "maya_scene": str(scene),
        "fbx_path": str(fbx),
        "anim_sequence": animation,
        "skeleton": skeleton,
        "track_count": int(unreal["track_count"]),
        "frame_count": int(unreal["frame_count"]),
        "fbx_sha256": output_hashes["fbx_path"],
        "unreal_asset_sha256": output_hashes["unreal_asset"],
    }
