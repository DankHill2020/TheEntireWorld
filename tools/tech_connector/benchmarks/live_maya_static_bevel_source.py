"""Create a disposable Maya static mesh and export through the registered FBX adapter."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import maya.standalone


PROOF_ROOT = Path(os.environ["TC_BEVEL_PROOF_ROOT"]).resolve()
PROOF_ROOT.mkdir(parents=True, exist_ok=True)
# Maya's userSetup starts the Tech Connector bridge during initialization.
# Keep its transient port records inside this disposable proof directory.
os.environ["MAYA_COMMAND_PORT"] = "17021"
os.environ["MAYA_COMMAND_PORT_SCAN_COUNT"] = "1"
os.environ["MAYA_COMMAND_PORT_FILE"] = str(PROOF_ROOT / "maya_port.txt")
os.environ["MAYA_COMMAND_SESSION_FILE"] = str(PROOF_ROOT / "maya_sessions.json")

maya.standalone.initialize(name="python")
import maya.cmds as cmds  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

def main() -> None:
    destination = PROOF_ROOT
    source = destination / "maya_source_cube.fbx"
    report = destination / "maya_source_receipt.json"
    if source.exists() or report.exists():
        raise FileExistsError("Refusing to overwrite a Maya source proof artifact")
    adapter = ROOT / "maya_tools" / "Animation" / "anim_export" / "bridge_export.py"
    spec = importlib.util.spec_from_file_location("tc_maya_bevel_export", adapter)
    if spec is None or spec.loader is None:
        raise RuntimeError("Maya FBX export adapter is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cmds.file(new=True, force=True)
    cube, _shape = cmds.polyCube(name="MayaPromptCube", width=2, height=2, depth=2)
    receipt = module.export_fbx(str(source), nodes=[cube], selected_only=True, bake_animation=False)
    payload = {
        "schema": "tech_connector.maya_bevel_source.v1",
        "maya_version": cmds.about(version=True),
        "mesh_name": cube,
        "export_receipt": receipt,
        "source_bytes": source.stat().st_size,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload), flush=True)


if __name__ == "__main__":
    main()
