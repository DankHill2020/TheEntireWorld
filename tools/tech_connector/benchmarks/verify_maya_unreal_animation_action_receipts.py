"""Bind the live action, source assets, and independent Maya/Unreal readbacks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result(rows: dict, key: str) -> dict:
    row = rows[key]
    if row.get("status") != "succeeded":
        raise RuntimeError(f"Action stage failed: {key}")
    return row["raw_result"]["result"]


def main() -> None:
    proof = Path(os.environ["TC_ANIMATION_ACTION_ROOT"]).resolve()
    output = proof / "receipt_chain.json"
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    maya_reopen = json.loads((proof / "maya_reopen.json").read_text(encoding="utf-8"))
    unreal_reopen = json.loads((proof / "unreal_reopen.json").read_text(encoding="utf-8"))
    if (report.get("schema") != "tech_connector.maya_unreal_animation_action.v1"
            or report.get("status_counts") != {"completed": 3}
            or report.get("passed") is not True):
        raise RuntimeError("Action execution did not complete three stages")
    clip = report.get("clip")
    if clip not in {"TesBoi", "FakeGameplay"}:
        raise RuntimeError("Unsupported proof clip")
    rows = report["action_report"]["results"]
    maya = _result(rows, "stage_01_maya_animation_fbx_to_engine")
    imported = _result(rows, "stage_02_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified")
    readback = _result(rows, "stage_03_unreal_unreal_tools_asset_transfer_adapter_registry_readback")
    source = Path(r"C:\depot\ArtSource\Exports\Animation\Gameplay") / f"{clip}.fbx"
    rig = Path(r"C:\depot\ArtSource\Rigs\Juice_rig_update.ma")
    hik = Path(r"C:\depot\ArtSource\Rigs\mocap_rigs\Juice_rig_update.fbx")
    for path in (source, rig, hik):
        if _hash(path) != report["input_sha256"][path.name]:
            raise RuntimeError(f"Selected input changed: {path}")
    scene = proof / f"{clip}_controls.ma"
    fbx = proof / f"{clip}_engine.fbx"
    for path in (scene, fbx):
        if _hash(path) != report["artifacts"][path.name]["sha256"]:
            raise RuntimeError(f"Action artifact changed: {path}")
    asset_path = f"/Game/TCProbe/{clip}ActionV1/{clip}_engine.{clip}_engine"
    skeleton_path = "/Game/TCProbe/Rig/Juice_rig_update_Skeleton.Juice_rig_update_Skeleton"
    clean = maya["clean_export"]
    if not (
        maya["transfer"]["animation_fbx"] == str(source)
        and maya["transfer"]["rig_scene"] == str(rig)
        and maya["transfer"]["target_hik_fbx"] == str(hik)
        and maya["transfer"]["source_characterization"] == "companion_hik"
        and maya["fbx_path"] == str(fbx)
        and maya["maya_scene"] == str(scene)
        and clean["ok"] is True
        and clean["joint_count"] == 295
        and clean["unwanted_joint_count"] == 0
        and clean["sample_frame_count"] == 21
        and clean["worst_translation_error"] < 0.5
        and clean["worst_rotation_error"] < 2.0
        and imported["source_file"] == maya["fbx_path"]
        and imported["asset_path"] == asset_path
        and imported["skeleton_path"] == skeleton_path
        and imported["track_count"] == 295
        and imported["frame_count"] == 80
        and readback["ok"] is True
        and readback["assets"] == [asset_path]
        and maya_reopen["ok"] is True
        and maya_reopen["control_scene_sha256"] == report["artifacts"][scene.name]["sha256"]
        and maya_reopen["rig_reference_count"] == 1
        and maya_reopen["keyed_control_count"] >= 61
        and maya_reopen["mapped_bone_count"] == 69
        and maya_reopen["sample_frame_count"] == 21
        and maya_reopen["worst_translation_error"] < 0.5
        and maya_reopen["worst_rotation_error"] < 2.0
        and unreal_reopen["ok"] is True
        and unreal_reopen["anim_sequence"] == asset_path
        and unreal_reopen["skeleton"] == skeleton_path
        and unreal_reopen["track_count"] == 295
        and unreal_reopen["frame_count"] == 80
    ):
        raise RuntimeError("Cross-host action receipt chain mismatch")
    motion = {row["bone"]: row for row in unreal_reopen["motion_samples"]}
    if (motion["pelvis"]["maximum_translation_delta"] < 1
            or motion["l_upperarm"]["maximum_rotation_delta_degrees"] < 1):
        raise RuntimeError("Fresh Unreal animation has no meaningful bone motion")
    asset_file = Path(report["asset_files"][0])
    if (len(report["asset_files"]) != 1 or not asset_file.is_file()
            or asset_file.name != f"{clip}_engine.uasset"):
        raise RuntimeError("Expected saved Unreal asset is missing")
    payload = {
        "schema": "tech_connector.maya_unreal_animation_action_receipt_chain.v1",
        "passed": True,
        "completed_stages": 3,
        "source_characterization": "companion_hik",
        "keyed_controls": maya_reopen["keyed_control_count"],
        "mapped_bones": maya_reopen["mapped_bone_count"],
        "maya_worst_translation_error": maya_reopen["worst_translation_error"],
        "maya_worst_rotation_error": maya_reopen["worst_rotation_error"],
        "clean_fbx_joints": clean["joint_count"],
        "unreal_asset": asset_path,
        "unreal_tracks": unreal_reopen["track_count"],
        "unreal_frames": unreal_reopen["frame_count"],
        "pelvis_translation_delta": motion["pelvis"]["maximum_translation_delta"],
        "left_upperarm_rotation_delta": motion["l_upperarm"]["maximum_rotation_delta_degrees"],
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
