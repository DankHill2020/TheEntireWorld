"""Publish and reload-verify a reference-based Maya animation source scene."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import maya.standalone

maya.standalone.initialize(name="python")

from maya_tools.Rigging.mocap.referenced_animation_scene import (  # noqa: E402
    publish_referenced_animation_source,
)


parser = argparse.ArgumentParser()
parser.add_argument("--work-scene", required=True, type=Path)
parser.add_argument("--published-rig-scene", required=True, type=Path)
parser.add_argument("--output-scene", required=True, type=Path)
args = parser.parse_args()

result = publish_referenced_animation_source(
    work_scene=args.work_scene,
    published_rig_scene=args.published_rig_scene,
    output_scene=args.output_scene,
)
print("AI_STUDIO_PUBLISHED_ANIMATION_SOURCE=" + json.dumps(result))
maya.standalone.uninitialize()
