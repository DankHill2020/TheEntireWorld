"""CLI wrapper for the registered data-driven Maya HumanIK retarget primitive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import maya.standalone

maya.standalone.initialize(name="python")

from maya_tools.Rigging.mocap.hik_retarget import retarget_fbx_hik  # noqa: E402


parser = argparse.ArgumentParser()
parser.add_argument("--target-rig", required=True, type=Path)
parser.add_argument("--source-fbx", required=True, type=Path)
parser.add_argument("--source-hik-fbx", type=Path)
parser.add_argument("--output-fbx", required=True, type=Path)
parser.add_argument("--source-mapping", type=Path)
parser.add_argument("--source-tpose-frame", type=float)
parser.add_argument("--target-character", default=None)
parser.add_argument("--source-character", default="AIStudioSourceCharacter")
parser.add_argument("--source-namespace", default="AIStudioSource")
parser.add_argument("--target-namespace", default="MannyRig_v01_retarget")
args = parser.parse_args()

source_mapping = None
if args.source_mapping:
    mapping_payload = json.loads(args.source_mapping.resolve().read_text(encoding="utf-8"))
    source_mapping = dict(mapping_payload.get("source_mapping") or mapping_payload)
report = retarget_fbx_hik(
    target_rig=str(args.target_rig),
    source_fbx=str(args.source_fbx),
    output_fbx=str(args.output_fbx),
    source_mapping=source_mapping,
    source_hik_fbx=str(args.source_hik_fbx) if args.source_hik_fbx else None,
    source_tpose_frame=args.source_tpose_frame,
    target_character=args.target_character,
    source_character=args.source_character,
    source_namespace=args.source_namespace,
    target_namespace=args.target_namespace,
)
print("AI_STUDIO_MAYA_HIK_RETARGET=" + json.dumps(report))
maya.standalone.uninitialize()
