"""Run one selected FBX -> Maya controls -> clean engine FBX handoff in mayapy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--animation-fbx", type=Path, required=True)
    parser.add_argument("--rig-scene", type=Path, required=True)
    parser.add_argument("--target-hik-fbx", type=Path, required=True)
    parser.add_argument("--source-hik-fbx", type=Path)
    parser.add_argument("--output-scene", type=Path, required=True)
    parser.add_argument("--output-fbx", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    args = parser.parse_args(argv)

    report = args.report_json.expanduser().resolve()
    protected = {
        path.expanduser().resolve()
        for path in (args.animation_fbx, args.rig_scene, args.target_hik_fbx,
                     args.source_hik_fbx, args.output_scene, args.output_fbx)
        if path is not None
    }
    scene = args.output_scene.expanduser().resolve()
    protected.update({
        scene.with_name(scene.stem + ".solved.fbx"),
        scene.with_name(scene.stem + ".hik_mapping.json"),
    })
    if report in protected:
        raise ValueError("Proof report must not alias an input or output asset")
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite proof report: {report}")

    import maya.standalone

    maya.standalone.initialize(name="python")
    try:
        from maya import cmds
        from maya_tools.Rigging.mocap.fbx_to_engine import transfer_fbx_to_engine
        from tech_connector.scripts.maya_fbx_to_control_rig import _reopen_audit

        result = transfer_fbx_to_engine(
            animation_fbx=args.animation_fbx,
            rig_scene=args.rig_scene,
            target_hik_fbx=args.target_hik_fbx,
            source_hik_fbx=args.source_hik_fbx,
            output_scene=args.output_scene,
            output_fbx=args.output_fbx,
        )
        transfer = result["transfer"]
        audit = _reopen_audit(
            Path(result["maya_scene"]), Path(transfer["rig_scene"]),
            Path(transfer["mapping_profile"]), result["frame_range"],
        )
        proof = {
            "ok": True,
            "maya_version": cmds.about(version=True),
            "animation_fbx": str(Path(args.animation_fbx).resolve()),
            "maya_scene": result["maya_scene"],
            "fbx_path": result["fbx_path"],
            "frame_range": result["frame_range"],
            "source_characterization": result["source_characterization"],
            "reopen_audit": audit,
            "clean_export": result["clean_export"],
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(proof, indent=2), encoding="utf-8")
        print("TC_MAYA_FBX_TO_ENGINE=" + json.dumps(proof))
        return 0
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
