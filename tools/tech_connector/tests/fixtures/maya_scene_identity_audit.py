"""Read-only identity audit for the Maya scene currently open in the UI."""

import json

import maya.cmds as cmds


references = []
for reference_node in cmds.ls(type="reference") or []:
    if reference_node == "sharedReferenceNode":
        continue
    try:
        references.append({
            "node": reference_node,
            "file": cmds.referenceQuery(reference_node, filename=True),
            "namespace": cmds.referenceQuery(reference_node, namespace=True),
            "loaded": bool(cmds.referenceQuery(reference_node, isLoaded=True)),
        })
    except Exception as exc:
        references.append({"node": reference_node, "error": str(exc)})

selection = []
for node in cmds.ls(selection=True, long=True) or []:
    matrix = cmds.xform(node, query=True, worldSpace=True, matrix=True)
    row = {
        "node": node,
        "type": cmds.nodeType(node),
        "world_position": matrix[12:15],
        "world_x": matrix[0:3],
        "world_y": matrix[4:7],
        "world_z": matrix[8:11],
    }
    for attribute in ("translate", "rotate", "jointOrient"):
        if cmds.attributeQuery(attribute, node=node, exists=True):
            row[attribute] = cmds.getAttr(node + "." + attribute)[0]
    selection.append(row)

print(json.dumps({
    "scene": cmds.file(query=True, sceneName=True),
    "modified": bool(cmds.file(query=True, modified=True)),
    "references": references,
    "selection": selection,
    "namespaces": cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or [],
    "roots": cmds.ls(assemblies=True, long=True) or [],
}, sort_keys=True))
