"""Run joint placer in the open Maya scene and audit positional preservation."""

import importlib
import json
import math
import traceback

import maya.cmds as cmds

from maya_tools.Rigging import joint_placer


OUTPUT_PATH = "C:/depot/tools/.joint_placer_live_compare.json"
POSITION_TOLERANCE = 1.0e-5


def _short(node):
    return node.split("|")[-1].split(":")[-1]


def _studio_root():
    candidates = [
        joint for joint in (cmds.ls(type="joint", long=True) or [])
        if _short(joint) == "origin"
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one studio origin joint; found {0}".format(
                len(candidates)
            )
        )
    return candidates[0]


def _body_mesh():
    candidates = []
    for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
        parent = (cmds.listRelatives(
            shape, parent=True, fullPath=True
        ) or [None])[0]
        if parent and _short(parent) == "Body_geo":
            candidates.append(parent)
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one Body_geo mesh; found {0}".format(
                len(candidates)
            )
        )
    return candidates[0]


def _capture(root):
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    return {
        _short(joint): {
            "position": [float(value) for value in cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            )],
            "matrix": [float(value) for value in cmds.xform(
                joint, query=True, worldSpace=True, matrix=True
            )],
            "rotate": [float(value) for value in cmds.getAttr(
                joint + ".rotate"
            )[0]],
            "jointOrient": [float(value) for value in cmds.getAttr(
                joint + ".jointOrient"
            )[0]],
        }
        for joint in joints
    }


selection = cmds.ls(selection=True, long=True) or []
scene = cmds.file(query=True, sceneName=True) or ""
mesh = _body_mesh()
before_root = _studio_root()
before = _capture(before_root)
report = {
    "scene": scene,
    "mesh": mesh,
    "before_joint_count": len(before),
    "before": before,
    "passed": False,
}

try:
    joint_placer = importlib.reload(joint_placer)
    result = joint_placer.build_basic_biped_skeleton(
        mesh=mesh,
        solver="production",
        replace_existing=True,
        create_guides=False,
        template_path=joint_placer.DEFAULT_PLACEMENT_TEMPLATE,
        template_namespace="",
        require_interior=False,
        joint_map=None,
        import_skin_weights=False,
    )
    after_root = result.root_joint
    after = _capture(after_root)
    deltas = {}
    missing = []
    for name, before_row in before.items():
        after_row = after.get(name)
        if after_row is None:
            missing.append(name)
            continue
        delta = math.sqrt(sum(
            (
                float(after_row["position"][index])
                - float(before_row["position"][index])
            ) ** 2
            for index in range(3)
        ))
        deltas[name] = delta
    offenders = {
        name: value for name, value in deltas.items()
        if value > POSITION_TOLERANCE
    }
    volume_report = {}
    if cmds.attributeQuery(
        joint_placer.STUDIO_VOLUME_REPORT_ATTR,
        node=after_root,
        exists=True,
    ):
        volume_report = json.loads(cmds.getAttr(
            after_root + "." + joint_placer.STUDIO_VOLUME_REPORT_ATTR
        ) or "{}")
    report.update({
        "after_joint_count": len(after),
        "after": after,
        "maximum_position_delta": max(deltas.values()) if deltas else 0.0,
        "position_tolerance": POSITION_TOLERANCE,
        "position_offenders": offenders,
        "missing_after": missing,
        "new_after": sorted(set(after) - set(before)),
        "approved_positions_locked": volume_report.get(
            "approved_positions_locked"
        ),
        "approved_positions_final_restore": volume_report.get(
            "approved_positions_final_restore"
        ),
        "final_joint_placement": volume_report.get("final_joint_placement"),
        "passed": not offenders and not missing,
    })
except Exception as exc:
    report.update({
        "error": str(exc),
        "traceback": traceback.format_exc(),
    })
finally:
    existing_selection = [node for node in selection if cmds.objExists(node)]
    if existing_selection:
        cmds.select(existing_selection, replace=True)
    else:
        cmds.select(clear=True)
    with open(OUTPUT_PATH, "w") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)

summary = {
    key: report.get(key)
    for key in (
        "scene",
        "mesh",
        "before_joint_count",
        "after_joint_count",
        "maximum_position_delta",
        "position_tolerance",
        "position_offenders",
        "missing_after",
        "new_after",
        "approved_positions_locked",
        "approved_positions_final_restore",
        "final_joint_placement",
        "passed",
        "error",
        "traceback",
    )
    if key in report
}
print("MAYA_JOINT_PLACER_LIVE=" + json.dumps(summary, sort_keys=True))
