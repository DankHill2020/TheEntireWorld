"""Validate rig export scope in real Maya without relying on its GUI event loop."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "tech_connector" / "benchmarks" / "results" / "maya_scope_20261020"
RESULTS.mkdir(parents=True, exist_ok=True)
SESSION_PATH = RESULTS / "bridge_session.json"
os.environ["TECH_CONNECTOR_BRIDGE_SESSION_FILE"] = str(SESSION_PATH)
os.environ["MAYA_COMMAND_PORT"] = "7009"
os.environ["MAYA_COMMAND_PORT_SCAN_COUNT"] = "1"
os.environ["MAYA_COMMAND_PORT_FILE"] = str(RESULTS / "maya_port.txt")
os.environ["MAYA_COMMAND_SESSION_FILE"] = str(RESULTS / "maya_sessions.json")

import maya.standalone  # noqa: E402

maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402

from maya_tools.Rigging.validation_proxy import create_rigged_proxy  # noqa: E402
from maya_tools.Animation.anim_export.bridge_export import export_fbx  # noqa: E402
from tech_connector.bridges.maya.maya_bridge import MayaBridge  # noqa: E402
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import (  # noqa: E402
    _read_dcc_export_scope,
)


def execute_inline(_self, code, *, port, timeout):
    del port, timeout
    output = io.StringIO()
    namespace = {"__name__": "__maya_scope_smoke__"}
    with contextlib.redirect_stdout(output):
        exec(code, namespace, namespace)
    return True, output.getvalue().strip()


try:
    fixture = create_rigged_proxy(start_frame=1, end_frame=24)
    selected_before = cmds.ls(selection=True) or []
    MayaBridge.execute_on_port = execute_inline
    selected_for_export = _read_dcc_export_scope(
        "maya",
        {"scope": "rig_contents", "subject": "skeletal_mesh", "label": "Rig contents"},
        session_port=7009,
        timeout_seconds=5.0,
    )
    fbx = RESULTS / "rig_scope_proxy.fbx"
    export_receipt = export_fbx(
        str(fbx), start_frame=1, end_frame=24, nodes=selected_for_export,
    )
    blender_code = (
        "import bpy,json; "
        f"bpy.ops.import_scene.fbx(filepath={str(fbx)!r}); "
        "print('TC_REIMPORT_RIG',json.dumps({"
        "'meshes':[o.name for o in bpy.data.objects if o.type=='MESH' and o.name!='Cube'],"
        "'armatures':[o.name for o in bpy.data.objects if o.type=='ARMATURE'],"
        "'actions':[a.name for a in bpy.data.actions]}))"
    )
    reimport = subprocess.run(
        [r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
         "--background", "--factory-startup", "--python-expr", blender_code],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30.0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    blender_readback = {}
    for line in reimport.stdout.splitlines():
        if line.startswith("TC_REIMPORT_RIG "):
            blender_readback = json.loads(line.removeprefix("TC_REIMPORT_RIG "))
    report = {
        "fixture": fixture,
        "selected_before": selected_before,
        "selected_for_export": selected_for_export,
        "includes_mesh": any("AIStudio_Proxy_Mesh" in name for name in selected_for_export),
        "includes_root_joint": any("AIStudio_Proxy_Root" in name for name in selected_for_export),
        "includes_tip_joint": any("AIStudio_Proxy_Tip" in name for name in selected_for_export),
        "excludes_material": all("Material" not in name for name in selected_for_export),
        "export_receipt": export_receipt,
        "fbx_bytes": fbx.stat().st_size if fbx.is_file() else 0,
        "blender_reimport_exit_code": reimport.returncode,
        "blender_readback": blender_readback,
    }
    (RESULTS / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "fixture"}))
    assert all(report[key] for key in (
        "includes_mesh", "includes_root_joint", "includes_tip_joint", "excludes_material",
    ))
    assert report["fbx_bytes"] > 0 and reimport.returncode == 0
    assert blender_readback.get("meshes") and blender_readback.get("armatures")
finally:
    SESSION_PATH.unlink(missing_ok=True)
