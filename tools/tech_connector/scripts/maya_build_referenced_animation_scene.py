"""Create a reference-based Maya animation scene and bake solved motion to controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import maya.standalone

maya.standalone.initialize(name="python")

from maya_tools.Rigging.mocap.referenced_animation_scene import (  # noqa: E402
    build_referenced_animation_scene,
)


parser = argparse.ArgumentParser()
parser.add_argument("--rig-scene", required=True, type=Path)
parser.add_argument("--solved-animation-fbx", required=True, type=Path)
parser.add_argument("--output-scene", required=True, type=Path)
parser.add_argument("--rig-namespace", default="CharacterRig")
parser.add_argument("--solved-namespace", default="RetargetSolved")
parser.add_argument("--rig-adapter", default="create_rig")
parser.add_argument("--mapping-json", required=True, type=Path)
parser.add_argument("--start-frame", type=float)
parser.add_argument("--end-frame", type=float)
args = parser.parse_args()

result = build_referenced_animation_scene(
    rig_scene=args.rig_scene,
    solved_animation_fbx=args.solved_animation_fbx,
    output_scene=args.output_scene,
    rig_namespace=args.rig_namespace,
    solved_namespace=args.solved_namespace,
    rig_adapter=args.rig_adapter,
    mapping_profile=args.mapping_json,
    start_frame=args.start_frame,
    end_frame=args.end_frame,
)
print("AI_STUDIO_REFERENCED_ANIMATION_SCENE=" + json.dumps(result))
maya.standalone.uninitialize()
