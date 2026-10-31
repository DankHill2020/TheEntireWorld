"""Fresh Unreal registry/class readback for the six-stage bevel prompt."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import unreal


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from unreal_tools.asset_transfer_adapter import registry_readback  # noqa: E402


def main() -> None:
    proof = Path(os.environ["TC_BEVEL_ACTION_ROOT"]).resolve()
    output = proof / "unreal_reopen.json"
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    if report.get("schema") != "tech_connector.maya_blender_unreal_bevel_action.v1" or not report.get("passed"):
        raise RuntimeError("Action report did not pass")
    results = report["action_report"]["results"]
    imported = results[
        "stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified"
    ]["raw_result"]["result"]
    path = str(imported["asset_path"])
    source = Path(imported["source_file"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != report["artifacts"][source.name]["sha256"]:
        raise RuntimeError("Action-engine source FBX changed after import")
    readback = registry_readback([path])
    asset = unreal.load_asset(path)
    if not readback["ok"] or not isinstance(asset, unreal.StaticMesh):
        raise RuntimeError(f"Persisted Unreal StaticMesh failed fresh readback: {path}")
    payload = {
        "schema": "tech_connector.maya_blender_unreal_bevel_action_reopen.v1",
        "asset_path": asset.get_path_name(),
        "asset_class": asset.get_class().get_name(),
        "registry_readback": readback,
        "source_sha256": report["artifacts"][source.name]["sha256"],
        "engine_version": unreal.SystemLibrary.get_engine_version(),
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "asset": payload["asset_path"]}))


if __name__ == "__main__":
    main()
