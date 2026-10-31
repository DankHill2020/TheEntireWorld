"""Independently check a prompt-bound Maya FBX-to-control-rig proof receipt.

The Maya scene pose audit is performed by the producer after reopening its
saved scene. This verifier checks that the receipt still matches the selected
inputs and saved output; it does not substitute for a fresh Maya UI test.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from maya_tools.Rigging.mocap.control_identity import is_animator_control_identity


SCHEMA = "tech_connector.maya_fbx_control_proof.v2"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Proof is missing a selected asset path")
    return Path(value).expanduser().resolve()


def verify_maya_fbx_control_prompt_proof(report_path: str | Path) -> dict:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schema") != SCHEMA or report.get("ok") is not True:
        raise ValueError("Not a successful Maya FBX-to-control-rig proof")
    binding = report.get("prompt_binding") or {}
    text = binding.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Proof has no bound custom prompt")
    decision = classify_prompt_route(text)
    if (decision.route != "dcc_execute"
            or decision.target_identifier != "animation.fbx_to_control_rig"
            or binding.get("route") != decision.route
            or binding.get("operation") != decision.target_identifier):
        raise ValueError("Prompt no longer classifies as the claimed Maya operation")
    selected = binding.get("selected_files") or {}
    hashes = report.get("input_sha256") or {}
    for role in ("animation_fbx", "rig_scene", "target_hik_fbx", "source_hik_fbx"):
        claimed = selected.get(role)
        parsed = (decision.keyword_args or {}).get(role)
        if claimed is None and parsed is None and role == "source_hik_fbx":
            if role in hashes:
                raise ValueError("Unexpected source-sister hash")
            continue
        path = _path(claimed)
        if path != _path(parsed):
            raise ValueError(f"Selected {role} no longer matches the prompt")
        if role != "source_hik_fbx" and path != _path(report.get(role)):
            raise ValueError(f"Selected {role} no longer matches the prompt or report")
        if not path.is_file() or _digest(path) != hashes.get(role):
            raise ValueError(f"Selected {role} is missing or changed")
    output = _path(selected.get("output_scene"))
    if output != _path((decision.keyword_args or {}).get("output_scene")) or output != _path(report.get("output_scene")):
        raise ValueError("Saved scene path no longer matches the prompt")
    if not output.is_file() or output.stat().st_size != report.get("output_bytes"):
        raise ValueError("Saved scene is missing or has changed size")
    if _digest(output) != report.get("output_sha256"):
        raise ValueError("Saved scene content changed after the Maya audit")
    audit = report.get("reopen_audit") or {}
    required_audit = {
        "rig_reference_count", "keyed_control_count", "animation_curve_count",
        "required_body_bone_count", "mapped_bone_count", "sample_frame_count",
        "worst_translation_error", "worst_rotation_error",
    }
    if not required_audit.issubset(audit):
        raise ValueError("Maya reopen audit is incomplete")
    keyed = audit.get("keyed_animator_controls")
    if (not isinstance(keyed, list)
            or len(keyed) != int(audit.get("keyed_control_count") or 0)
            or len({str(item.get("name") or "") for item in keyed if isinstance(item, dict)}) != len(keyed)
            or not all(
                isinstance(item, dict) and bool(str(item.get("name") or "").strip())
                and isinstance(item.get("object_sets"), list)
                and is_animator_control_identity(
                    str(item.get("name") or ""), item.get("object_sets") or ()
                ) for item in keyed
            )):
        raise ValueError("Maya reopen audit does not prove keyed animator-facing controls")
    translation_error = float(audit["worst_translation_error"])
    rotation_error = float(audit["worst_rotation_error"])
    if not all(math.isfinite(value) and value >= 0 for value in (translation_error, rotation_error)):
        raise ValueError("Maya reopen audit has invalid pose errors")
    if (audit.get("rig_reference_count") != 1
            or int(audit.get("keyed_control_count") or 0) < 1
            or int(audit.get("animation_curve_count") or 0) < 1
            or int(audit.get("required_body_bone_count") or 0) < 17
            or int(audit.get("mapped_bone_count") or 0) < 17
            or int(audit.get("sample_frame_count") or 0) < 21
            or translation_error > 0.5
            or rotation_error > 2.0):
        raise ValueError("Maya reopen audit is missing or outside tolerance")
    frame_range = report.get("frame_range") or []
    if len(frame_range) != 2 or float(frame_range[1]) <= float(frame_range[0]):
        raise ValueError("Proof has no animation frame range")
    if "source_hik_slots" in report or "target_hik_slots" in report:
        for role in ("source_hik_slots", "target_hik_slots"):
            slots = report.get(role)
            if (not isinstance(slots, list) or len(slots) < 17
                    or "Hips" not in slots or len(set(slots)) != len(slots)):
                raise ValueError(f"Proof has invalid {role}")
        hips = report.get("source_stance_hips")
        if (not isinstance(hips, (list, tuple)) or len(hips) != 3
                or not all(math.isfinite(float(value)) for value in hips)):
            raise ValueError("Proof has invalid source HIK stance")
        tpose_frame = report.get("source_tpose_frame")
        if tpose_frame is not None and not float(frame_range[0]) <= float(tpose_frame) <= float(frame_range[1]):
            raise ValueError("Source T-pose frame is outside the animation")
    return {
        "verified": True,
        "output_scene": str(output),
        "output_sha256": report["output_sha256"],
        "keyed_control_count": audit["keyed_control_count"],
        "source_characterization": report.get("source_characterization"),
        "source_hik_slot_count": len(report.get("source_hik_slots") or []),
    }
