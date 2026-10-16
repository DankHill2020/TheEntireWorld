"""Mayapy command-line runner for the joint-placement regression corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import maya.standalone

TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))


def _resolve(value: str, base: Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return str(path.resolve()).replace("\\", "/")


def _import_fbx_in_namespace(cmds, scene: str, namespace: str) -> None:
    """Import FBX DAG nodes into a predictable namespace.

    Maya 2023's FBX plug-in can ignore the ``cmds.file(namespace=...)`` flag.
    Capture the imported nodes and namespace their transforms/joints explicitly so
    source skeleton names cannot collide with the studio template built afterward.
    """
    namespace = str(namespace or "source").strip(":") or "source"
    if not cmds.namespace(exists=namespace):
        cmds.namespace(add=namespace)
    imported = cmds.file(
        scene,
        i=True,
        type="FBX",
        ignoreVersion=True,
        mergeNamespacesOnClash=False,
        returnNewNodes=True,
    ) or []
    dag_nodes = []
    for node_type in ("joint", "transform"):
        dag_nodes.extend(cmds.ls(imported, type=node_type, long=True) or [])
    for node in sorted(set(dag_nodes), key=lambda value: value.count("|"), reverse=True):
        if not cmds.objExists(node):
            continue
        leaf = node.rsplit("|", 1)[-1]
        if ":" in leaf:
            continue
        cmds.rename(node, "{0}:{1}".format(namespace, leaf))


def run_manifest(manifest_path: str):
    from maya_tools.Rigging import joint_placement_regression as regression

    import maya.cmds as cmds

    manifest_source = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != regression.SCHEMA_VERSION:
        raise RuntimeError("Unsupported regression manifest schema.")
    results = []
    for entry in manifest.get("cases", []):
        case_id = str(entry.get("id") or "unnamed")
        try:
            scene = _resolve(entry["scene"], manifest_source.parent)
            baseline = _resolve(entry["baseline"], manifest_source.parent)
            template = _resolve(
                entry.get("template", regression.joint_placer.DEFAULT_PLACEMENT_TEMPLATE),
                manifest_source.parent,
            )
            cmds.file(new=True, force=True)
            if Path(scene).suffix.lower() == ".fbx":
                try:
                    cmds.loadPlugin("fbxmaya", quiet=True)
                except Exception:
                    pass
                _import_fbx_in_namespace(
                    cmds,
                    scene,
                    str(entry.get("source_namespace") or "source"),
                )
            else:
                cmds.file(scene, open=True, force=True, prompt=False)
            build_skeleton = bool(entry.get("build_skeleton", True))
            report = regression.evaluate_mesh_against_baseline(
                entry["mesh"],
                baseline,
                template_path=template,
                build_skeleton=build_skeleton,
            )
            foot_namespace = ""
            if not build_skeleton:
                foot_namespace = "__foot_contract__"
                regression.joint_placer.build_basic_biped_skeleton(
                    entry["mesh"],
                    solver="production",
                    template_path=template,
                    template_namespace=foot_namespace,
                    replace_existing=True,
                    create_guides=False,
                    require_interior=False,
                )
            foot_contract = regression.evaluate_studio_foot_contract(
                namespace=foot_namespace,
                mesh=entry["mesh"],
            )
            report["foot_contract"] = foot_contract
            if not foot_contract["passed"]:
                report["failures"].extend(
                    "foot contract: " + failure
                    for failure in foot_contract["failures"]
                )
                report["passed"] = False
            pelvis_contract = regression.evaluate_studio_pelvis_contract(
                entry["mesh"],
                namespace=foot_namespace,
            )
            report["pelvis_contract"] = pelvis_contract
            if not pelvis_contract["passed"]:
                report["failures"].extend(
                    "pelvis contract: " + failure
                    for failure in pelvis_contract["failures"]
                )
                report["passed"] = False
            report["case_id"] = case_id
            report["scene"] = scene
        except Exception as exc:
            report = {
                "case_id": case_id,
                "passed": False,
                "failures": ["runner exception: {0}".format(exc)],
            }
        results.append(report)
    passed = sum(bool(result.get("passed")) for result in results)
    return {
        "schema_version": regression.SCHEMA_VERSION,
        "manifest": str(manifest_source).replace("\\", "/"),
        "passed": passed == len(results) and bool(results),
        "summary": {
            "case_count": len(results),
            "passed_count": passed,
            "failed_count": len(results) - passed,
        },
        "cases": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    maya.standalone.initialize(name="python")
    try:
        report = run_manifest(args.manifest)
        destination = Path(args.report).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report["summary"], sort_keys=True))
        return 0 if report["passed"] else 1
    finally:
        maya.standalone.uninitialize()


if __name__ == "__main__":
    sys.exit(main())
