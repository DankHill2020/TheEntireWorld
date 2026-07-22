"""Generate and validate a reusable HIK mapping profile from an FBX skeleton."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import maya.standalone

maya.standalone.initialize(name="python")
from maya import cmds, mel  # noqa: E402

from maya_tools.Rigging.mocap import hik_mapping, setup_hik  # noqa: E402


def bare_name(node):
    return str(node).split("|")[-1].split(":")[-1]


parser = argparse.ArgumentParser()
parser.add_argument("--source-fbx", required=True, type=Path)
parser.add_argument("--output-json", required=True, type=Path)
parser.add_argument("--profile-name", required=True)
parser.add_argument("--root-bone", default="root")
args = parser.parse_args()

source = args.source_fbx.expanduser().resolve()
output = args.output_json.expanduser().resolve()
if not source.is_file():
    raise FileNotFoundError(source)

cmds.file(new=True, force=True)
cmds.loadPlugin("fbxmaya", quiet=True)
mel.eval("FBXResetImport;")
mel.eval('FBXImport -f "{}";'.format(str(source).replace("\\", "/")))

matches = [
    joint for joint in (cmds.ls(type="joint", long=True) or [])
    if bare_name(joint) == args.root_bone
]
roots = [
    joint for joint in matches
    if not (cmds.listRelatives(joint, parent=True, type="joint") or [])
]
root = (roots or matches or [None])[0]
if not root:
    raise RuntimeError(f"Skeleton has no root bone named {args.root_bone}")

detected = setup_hik.guess_joint_map_from_root(root)
resolved, validation = hik_mapping.resolve_to_scene(detected, root)
if validation["unresolved"] or validation["missing_required"]:
    raise RuntimeError(
        "Generated HIK profile failed validation: " + json.dumps(validation)
    )

portable_mapping = {
    slot: {
        "index": int(row["index"]),
        "joint": hik_mapping.unqualified_name(row.get("joint") or ""),
    }
    for slot, row in resolved.items()
}
payload = {
    "schema_version": 1,
    "profile_name": args.profile_name,
    "mapping": portable_mapping,
    "provenance": {
        "method": "validated_hierarchy_name_inference",
        "source_fbx": str(source),
        "source_root": bare_name(root),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator": "tech_connector/scripts/maya_generate_hik_mapping_profile.py",
    },
    "validation": validation,
}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(
    "AI_STUDIO_HIK_MAPPING_PROFILE="
    + json.dumps({
        "ok": output.is_file(),
        "output_json": str(output),
        "mapped_slot_count": validation["mapped_slot_count"],
        "validation": validation,
    })
)
maya.standalone.uninitialize()
