"""Run and independently reopen-check FBX -> HIK -> Maya control-rig transfer.

Run with Maya's mayapy, not system Python. Inputs remain untouched; output
overwrites require --overwrite. The JSON line is compact enough for a prompt
runner to capture as demo proof, while --report-json retains the full record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--animation-fbx", required=True, type=Path)
    parser.add_argument("--rig-scene", required=True, type=Path)
    parser.add_argument("--target-hik-fbx", required=True, type=Path)
    parser.add_argument("--source-hik-fbx", type=Path)
    parser.add_argument("--source-mapping", type=Path)
    parser.add_argument("--source-tpose-frame", type=float)
    parser.add_argument("--mapping-profile", type=Path)
    parser.add_argument("--output-scene", required=True, type=Path)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--prompt", help="Bind a complete Maya transfer prompt to the selected files")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _prompt_binding(prompt: str, args: argparse.Namespace) -> dict:
    """Reject a prompt whose resolved file roles differ from the selected assets."""
    from tech_connector.services.prompt.prompt_route_service import classify_prompt_route

    decision = classify_prompt_route(prompt)
    if (decision.route != "dcc_execute"
            or decision.target_identifier != "animation.fbx_to_control_rig"
            or not decision.requires_confirmation):
        raise ValueError("Prompt is not a complete executable Maya FBX-to-control-rig request")
    selected = {
        "animation_fbx": args.animation_fbx,
        "rig_scene": args.rig_scene,
        "target_hik_fbx": args.target_hik_fbx,
        "source_hik_fbx": args.source_hik_fbx,
        "output_scene": args.output_scene,
    }
    parsed = decision.keyword_args or {}
    for role, path in selected.items():
        prompt_path = parsed.get(role)
        if (path is None) != (prompt_path is None):
            raise ValueError(f"Prompt and selected files disagree on {role}")
        if path is not None and Path(prompt_path).expanduser().resolve() != path.expanduser().resolve():
            raise ValueError(f"Prompt and selected files disagree on {role}")
    return {
        "text": prompt,
        "route": decision.route,
        "operation": decision.target_identifier,
        "selected_files": {role: str(path.expanduser().resolve()) if path else None
                           for role, path in selected.items()},
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reopen_audit(output_scene: Path, rig_scene: Path, profile_path: Path,
                  frame_range: list[float]) -> dict:
    from maya import cmds
    from maya_tools.Rigging.mocap import hik_mapping
    from maya_tools.Rigging.mocap import referenced_animation_scene as scene

    cmds.file(new=True, force=True)
    cmds.file(str(output_scene), open=True, force=True, prompt=False)
    references = cmds.file(query=True, reference=True) or []
    matching = [item for item in references
                if Path(item.split("{")[0]).resolve() == rig_scene.resolve()]
    if len(matching) != 1:
        raise RuntimeError("Reopened scene did not retain exactly one selected rig reference")
    controls = scene._referenced_rig_transforms("CharacterRig")
    keyed_controls = [node for node in controls
                      if scene._is_animator_control(node)
                      and (cmds.keyframe(node, query=True, keyframeCount=True) or 0)]
    if not keyed_controls:
        raise RuntimeError("Reopened rig has no keyed animator controls")
    source = scene._source_joint_map("RetargetSolved")
    deform = scene._referenced_rig_joint_map("CharacterRig")
    profile = hik_mapping.load_profile(str(profile_path))
    mapped = {scene._bare(row["joint"]) for row in profile.values()
              if (row or {}).get("joint")}
    required = {scene._bare(profile[slot]["joint"])
                for slot in hik_mapping.REQUIRED_BODY_SLOTS
                if (profile.get(slot) or {}).get("joint")}
    if not required or not mapped.issubset(source.keys() & deform.keys()):
        raise RuntimeError("Reopened scene is missing mapped HIK joints")
    start, end = map(float, frame_range)
    sample_frames = [start + (end - start) * index / 20.0 for index in range(21)]
    worst_translation = 0.0
    worst_rotation = 0.0
    for frame in sample_frames:
        cmds.currentTime(frame, edit=True)
        for bone in mapped:
            source_t = cmds.xform(source[bone], query=True, worldSpace=True, translation=True)
            deform_t = cmds.xform(deform[bone], query=True, worldSpace=True, translation=True)
            worst_translation = max(worst_translation, scene._vector_error(source_t, deform_t))
            worst_rotation = max(worst_rotation, scene._world_rotation_error(source[bone], deform[bone]))
    if worst_translation > 0.5 or worst_rotation > 2.0:
        raise RuntimeError(
            f"Reopened pose mismatch: translation={worst_translation:.4f}, "
            f"rotation={worst_rotation:.4f}"
        )
    return {
        "rig_reference_count": len(matching),
        "keyed_control_count": len(keyed_controls),
        "keyed_animator_controls": [
            {"name": scene._bare(node), "object_sets": sorted(cmds.listSets(object=node) or [])}
            for node in keyed_controls
        ],
        "animation_curve_count": len(cmds.ls(type="animCurve") or []),
        "required_body_bone_count": len(required),
        "mapped_bone_count": len(mapped),
        "sample_frame_count": len(sample_frames),
        "worst_translation_error": worst_translation,
        "worst_rotation_error": worst_rotation,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    prompt_binding = _prompt_binding(args.prompt, args) if args.prompt else None
    report_path = args.report_json.expanduser().resolve() if args.report_json else None
    if report_path is not None:
        protected = {
            path.expanduser().resolve()
            for path in (
                args.animation_fbx, args.rig_scene, args.target_hik_fbx,
                args.source_hik_fbx, args.source_mapping, args.mapping_profile,
                args.output_scene,
                args.output_scene.with_name(args.output_scene.stem + ".solved.fbx"),
                args.output_scene.with_name(args.output_scene.stem + ".hik_mapping.json"),
            )
            if path is not None
        }
        if report_path in protected:
            raise ValueError(f"Proof report path aliases an input or output asset: {report_path}")
        if report_path.exists() and not args.overwrite:
            raise FileExistsError(f"Refusing to overwrite report: {report_path}")
    input_paths = {
        "animation_fbx": args.animation_fbx,
        "rig_scene": args.rig_scene,
        "target_hik_fbx": args.target_hik_fbx,
        "source_hik_fbx": args.source_hik_fbx,
    }
    input_hashes = {role: _sha256(path.expanduser().resolve())
                    for role, path in input_paths.items() if path is not None}
    source_mapping = None
    if args.source_mapping is not None:
        payload = json.loads(args.source_mapping.resolve().read_text(encoding="utf-8"))
        source_mapping = dict(payload.get("source_mapping") or payload)

    import maya.standalone
    maya.standalone.initialize(name="python")
    try:
        from maya import cmds
        from maya_tools.Rigging.mocap.fbx_to_control_rig import transfer_fbx_animation_to_control_rig

        transfer = transfer_fbx_animation_to_control_rig(
            animation_fbx=args.animation_fbx,
            rig_scene=args.rig_scene,
            target_hik_fbx=args.target_hik_fbx,
            source_hik_fbx=args.source_hik_fbx,
            source_mapping=source_mapping,
            source_tpose_frame=args.source_tpose_frame,
            mapping_profile=args.mapping_profile,
            output_scene=args.output_scene,
            overwrite=args.overwrite,
        )
        audit = _reopen_audit(
            Path(transfer["output_scene"]), Path(transfer["rig_scene"]),
            Path(transfer["mapping_profile"]), transfer["frame_range"],
        )
        for role, before in input_hashes.items():
            if _sha256(input_paths[role].expanduser().resolve()) != before:
                raise RuntimeError(f"Transfer modified selected input: {role}")
        evidence = {
            "ok": True,
            "schema": "tech_connector.maya_fbx_control_proof.v2",
            "animation_fbx": transfer["animation_fbx"],
            "source_characterization": transfer["source_characterization"],
            "source_hik_slots": sorted(transfer["source_slots"]),
            "target_hik_slots": sorted(transfer["target_slots"]),
            "source_stance_hips": transfer["source_stance_hips"],
            "source_tpose_frame": transfer["hik_retarget"].get("source_tpose_frame"),
            "rig_scene": transfer["rig_scene"],
            "target_hik_fbx": transfer["target_hik_fbx"],
            "output_scene": transfer["output_scene"],
            "output_bytes": Path(transfer["output_scene"]).stat().st_size,
            "output_sha256": _sha256(Path(transfer["output_scene"])),
            "input_sha256": input_hashes,
            "solved_fbx": transfer["solved_fbx"],
            "frame_range": transfer["frame_range"],
            "companion_transfer": transfer["hik_retarget"].get("companion_transfer"),
            "control_binding_count": transfer["control_bake"]["bake"]["binding_count"],
            "rig_modes": transfer["control_bake"]["bake"]["rig_modes"],
            "ribbon_calibrations": transfer["control_bake"]["bake"]["ribbon_calibrations"],
            "maya_version": cmds.about(version=True),
            "reopen_audit": audit,
        }
        if prompt_binding is not None:
            evidence["prompt_binding"] = prompt_binding
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print("TECH_CONNECTOR_MAYA_FBX_TO_CONTROLS=" + json.dumps(evidence))
        return 0
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
