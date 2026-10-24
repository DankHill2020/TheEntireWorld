"""Export a clean, independently audited FBX skeleton from an edited Maya rig.

Run with mayapy. The source Maya scene remains untouched; --overwrite is
required to replace an existing FBX or proof report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-scene", type=Path, required=True)
    parser.add_argument("--output-fbx", type=Path, required=True)
    parser.add_argument("--start-frame", type=int, required=True)
    parser.add_argument("--end-frame", type=int, required=True)
    parser.add_argument("--rig-namespace", default="CharacterRig")
    parser.add_argument("--solved-namespace", default="RetargetSolved")
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    paths = [args.source_scene.resolve(), args.output_fbx.resolve()]
    if args.report_json is not None:
        report_path = args.report_json.resolve()
        if report_path in paths:
            raise ValueError("Proof report path aliases source scene or export FBX")
        if report_path.exists() and not args.overwrite:
            raise FileExistsError(f"Refusing to overwrite report: {report_path}")

    import maya.standalone
    maya.standalone.initialize(name="python")
    try:
        from maya import cmds
        from maya_tools.Animation.anim_export.clean_skeleton_export import export_control_rig_skeleton

        evidence = export_control_rig_skeleton(
            args.source_scene, args.output_fbx,
            start_frame=args.start_frame, end_frame=args.end_frame,
            rig_namespace=args.rig_namespace,
            solved_namespace=args.solved_namespace,
            overwrite=args.overwrite,
        )
        evidence["maya_version"] = cmds.about(version=True)
        if args.report_json is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print("TECH_CONNECTOR_MAYA_ENGINE_FBX=" + json.dumps(evidence))
        return 0
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
