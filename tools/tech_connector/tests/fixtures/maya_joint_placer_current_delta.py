"""Compare the current Maya studio skeleton to the saved live-run baseline."""

import json
import math

import maya.cmds as cmds


REPORT_PATH = "C:/depot/tools/.joint_placer_live_compare.json"


def _short(node):
    return node.split("|")[-1].split(":")[-1]


with open(REPORT_PATH, "r") as stream:
    baseline = json.load(stream).get("before") or {}

current = {}
for joint in cmds.ls(type="joint", long=True) or []:
    name = _short(joint)
    if name not in baseline:
        continue
    current[name] = [float(value) for value in cmds.xform(
        joint, query=True, worldSpace=True, translation=True
    )]

deltas = {}
for name, before_row in baseline.items():
    if name not in current:
        continue
    deltas[name] = math.sqrt(sum(
        (current[name][index] - float(before_row["position"][index])) ** 2
        for index in range(3)
    ))

print(json.dumps({
    "compared": len(deltas),
    "missing": sorted(set(baseline) - set(current)),
    "maximum_position_delta": max(deltas.values()) if deltas else None,
    "offenders_over_1e_5": {
        name: delta for name, delta in deltas.items() if delta > 1.0e-5
    },
}, sort_keys=True))
