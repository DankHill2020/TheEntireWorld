"""Build the current create_rig implementation on an exact source hierarchy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import maya.standalone

maya.standalone.initialize(name="python")
from maya import cmds, mel  # noqa: E402

from maya_tools.Rigging import create_rig  # noqa: E402
from maya_tools.Rigging.mocap import setup_hik  # noqa: E402
from maya_tools.Rigging.mocap import hik_mapping  # noqa: E402


def short_name(node):
    return str(node).split("|")[-1].split(":")[-1]


def find_root(name):
    matches = [
        node for node in (cmds.ls(type="joint", long=True) or [])
        if short_name(node) == name
    ]
    roots = [node for node in matches if not (cmds.listRelatives(node, parent=True, type="joint") or [])]
    return (roots or matches or [None])[0]


parser = argparse.ArgumentParser()
parser.add_argument("--source-fbx", required=True, type=Path)
parser.add_argument("--output-scene", required=True, type=Path)
parser.add_argument("--root-bone", default="root")
parser.add_argument("--mapping-json", type=Path)
args = parser.parse_args()

source = args.source_fbx.resolve()
output = args.output_scene.resolve()
if not source.is_file():
    raise FileNotFoundError(source)
output.parent.mkdir(parents=True, exist_ok=True)

cmds.file(new=True, force=True)
cmds.loadPlugin("fbxmaya", quiet=True)
mel.eval("FBXResetImport;")
mel.eval('FBXImport -f "{}";'.format(str(source).replace("\\", "/")))
root = find_root(args.root_bone)
if not root:
    raise RuntimeError(f"Source hierarchy has no root bone named {args.root_bone}")

required = {
    "Reference", "Hips", "Spine", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
}
mapping_report = {}
if args.mapping_json:
    mapping_path = args.mapping_json.resolve()
    if not mapping_path.is_file():
        raise FileNotFoundError(mapping_path)
    body_map = hik_mapping.load_profile(str(mapping_path))
    body_map, mapping_report = hik_mapping.resolve_to_scene(body_map, root)
    mapping_source = "mapping_json:" + str(mapping_path)
else:
    character_maps = []
    for character in cmds.ls(type="HIKCharacterNode") or []:
        mapping = hik_mapping.from_character_definition(character)
        mapping, report = hik_mapping.resolve_to_scene(mapping, root)
        mapped_required = sum(bool((mapping.get(slot) or {}).get("joint")) for slot in required)
        character_maps.append((mapped_required, character, mapping, report))
    character_maps.sort(key=lambda row: (-row[0], row[1]))
    if character_maps and character_maps[0][0] == len(required):
        mapping_source = "embedded_hik_character:" + character_maps[0][1]
        body_map = character_maps[0][2]
        mapping_report = character_maps[0][3]
    else:
        mapping_source = "hierarchy_name_inference"
        body_map = setup_hik.guess_joint_map_from_root(root)
        body_map, mapping_report = hik_mapping.resolve_to_scene(body_map, root)
missing = sorted(slot for slot in required if not (body_map.get(slot) or {}).get("joint"))
if missing:
    raise RuntimeError("Required create_rig mappings are missing: " + ", ".join(missing))

create_rig.create_rig_from_mapping(body_map, {}, prepare_t_pose=False)
controls = sorted(
    node for node in (cmds.ls(type="transform", long=True) or [])
    if node.split("|")[-1].endswith("_ctrl")
)
if not cmds.objExists(create_rig.MODULE_STORE_NODE) or not controls:
    raise RuntimeError("create_rig did not create its metadata node and animator controls")

file_type = "mayaAscii" if output.suffix.lower() == ".ma" else "mayaBinary"
cmds.file(rename=str(output))
cmds.file(save=True, force=True, type=file_type)
report = {
    "ok": output.is_file() and output.stat().st_size > 0,
    "source_fbx": str(source),
    "output_scene": str(output),
    "output_bytes": output.stat().st_size if output.exists() else 0,
    "root": root,
    "mapped_slots": sorted(slot for slot, row in body_map.items() if row.get("joint")),
    "mapping_source": mapping_source,
    "mapping_validation": mapping_report,
    "control_count": len(controls),
    "controls": controls,
    "metadata_node": create_rig.MODULE_STORE_NODE,
}
print("AI_STUDIO_INTERNAL_RIG_BUILD=" + json.dumps(report))
maya.standalone.uninitialize()
