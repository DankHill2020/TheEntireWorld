"""Fresh Maya process reopens and pose-audits the action-generated control scene."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import maya.standalone


def main() -> None:
    proof = Path(os.environ["TC_ANIMATION_ACTION_ROOT"]).resolve()
    output = proof / "maya_reopen.json"
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    if report.get("schema") != "tech_connector.maya_unreal_animation_action.v1" or not report.get("passed"):
        raise RuntimeError("Action report did not pass")
    result = report["action_report"]["results"]["stage_01_maya_animation_fbx_to_engine"]["raw_result"]["result"]
    transfer = result["transfer"]
    scene = Path(result["maya_scene"])
    profile = Path(transfer["mapping_profile"])
    if (hashlib.sha256(scene.read_bytes()).hexdigest()
            != report["artifacts"][scene.name]["sha256"]):
        raise RuntimeError("Control scene changed after action completion")
    maya.standalone.initialize(name="python")
    try:
        from maya_tools.Rigging.mocap.hik_mapping import REQUIRED_BODY_SLOTS
        from tech_connector.scripts.maya_fbx_to_control_rig import _reopen_audit

        audit = _reopen_audit(scene, Path(transfer["rig_scene"]), profile,
                              transfer["frame_range"])
        if (audit["rig_reference_count"] != 1
                or audit["keyed_control_count"] < 1
                or audit["mapped_bone_count"] < len(REQUIRED_BODY_SLOTS)
                or audit["sample_frame_count"] != 21):
            raise RuntimeError(f"Incomplete reopened rig audit: {audit}")
        payload = {
            "schema": "tech_connector.maya_unreal_animation_action_scene_reopen.v1",
            "ok": True,
            "control_scene_sha256": report["artifacts"][scene.name]["sha256"],
            "rig_reference_count": audit["rig_reference_count"],
            "keyed_control_count": audit["keyed_control_count"],
            "animation_curve_count": audit["animation_curve_count"],
            "mapped_bone_count": audit["mapped_bone_count"],
            "sample_frame_count": audit["sample_frame_count"],
            "worst_translation_error": audit["worst_translation_error"],
            "worst_rotation_error": audit["worst_rotation_error"],
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload))
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    main()
