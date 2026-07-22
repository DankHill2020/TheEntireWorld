"""Inspect FBX hierarchy and embedded HumanIK definitions in Maya standalone."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import maya.standalone

maya.standalone.initialize(name="python")

from maya import cmds, mel  # noqa: E402


parser = argparse.ArgumentParser()
parser.add_argument("fbx", type=Path)
args = parser.parse_args()
source = args.fbx.resolve()
cmds.loadPlugin("fbxmaya", quiet=True)
mel.eval("FBXResetImport;")
mel.eval('FBXImport -f "{}";'.format(str(source).replace("\\", "/")))

maya_location = Path(cmds.about(environmentFile=True)).parents[2]
for script in ("hikGlobalUtils.mel", "hikCharacterControlsUI.mel", "hikDefinitionOperations.mel"):
    candidate = Path(cmds.internalVar(userScriptDir=True)) / script
    try:
        mel.eval(f'source "{script}";')
    except Exception:
        if candidate.exists():
            mel.eval('source "{}";'.format(str(candidate).replace("\\", "/")))

try:
    characters = list(mel.eval("hikGetSceneCharacters()") or [])
except Exception:
    characters = []
core_slots = {
    "Hips": 1, "LeftUpLeg": 2, "LeftLeg": 3, "LeftFoot": 4,
    "RightUpLeg": 5, "RightLeg": 6, "RightFoot": 7, "Spine": 8,
    "LeftArm": 9, "LeftForeArm": 10, "LeftHand": 11,
    "RightArm": 12, "RightForeArm": 13, "RightHand": 14, "Head": 15,
    "LeftShoulder": 18, "RightShoulder": 19, "Neck": 20,
    "Spine1": 23, "Spine2": 24, "Spine3": 25,
}
character_mappings = {}
character_connections = {}
character_attributes = {}
for character in characters:
    slots = {}
    for label, index in core_slots.items():
        try:
            slots[label] = str(mel.eval(f'getCharacterObject("{character}", {index})') or "")
        except Exception as exc:
            slots[label] = "ERROR: " + str(exc)
    character_mappings[character] = slots
    character_connections[character] = list(
        cmds.listConnections(character, connections=True, plugs=True, source=True, destination=True) or []
    )
    character_attributes[character] = [
        value
        for value in (cmds.listAttr(character, connectable=True) or [])
        if any(term in value.lower() for term in ("hip", "spine", "arm", "leg", "hand", "foot", "head", "neck"))
    ]
joint_roots = [
    joint for joint in cmds.ls(type="joint", long=True) or []
    if not (cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or [])
]
joints = []
for joint in cmds.ls(type="joint", long=True) or []:
    parent = cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or []
    joints.append(
        {
            "path": joint,
            "name": joint.split("|")[-1].split(":")[-1],
            "parent": parent[0] if parent else "",
            "key_count": len(cmds.keyframe(joint, query=True, timeChange=True) or []),
        }
    )
report = {
    "ok": bool(joint_roots),
    "source": str(source),
    "characters": characters,
    "character_mappings": character_mappings,
    "character_connections": character_connections,
    "character_attributes": character_attributes,
    "hik_nodes": cmds.ls(type="HIKCharacterNode") or [],
    "joint_count": len(cmds.ls(type="joint") or []),
    "joint_roots": joint_roots,
    "joints": joints,
    "namespaces": [value for value in cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or [] if value not in {"UI", "shared"}],
    "playback": {
        "min": cmds.playbackOptions(query=True, min=True),
        "max": cmds.playbackOptions(query=True, max=True),
        "fps_unit": cmds.currentUnit(query=True, time=True),
    },
}
print("AI_STUDIO_MAYA_HIK_PROBE=" + json.dumps(report))
maya.standalone.uninitialize()
