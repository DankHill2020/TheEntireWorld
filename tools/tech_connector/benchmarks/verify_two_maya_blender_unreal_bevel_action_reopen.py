"""Fresh Unreal process verifies both saved assets from the 12-stage action."""

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
    output = proof / os.environ.get("TC_BEVEL_REOPEN_OUTPUT", "unreal_reopen.json")
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    if report.get("schema") != "tech_connector.two_maya_blender_unreal_bevel_action.v1" or not report.get("passed"):
        raise RuntimeError("Two-lane action report did not pass")
    results = report["action_report"]["results"]
    assets = []
    for name, stage in (("Crate_A", 5), ("Barrel_B", 11)):
        imported = results[f"stage_{stage:02d}_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified"]["raw_result"]["result"]
        source = Path(imported["source_file"])
        expected = report["artifacts"][source.name]["sha256"]
        if source.name != f"{name}_blender.fbx" or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Wrong or changed FBX source for {name}")
        path = imported["asset_path"]
        asset = unreal.load_asset(path)
        if not isinstance(asset, unreal.StaticMesh):
            raise RuntimeError(f"Persisted StaticMesh missing: {path}")
        assets.append({"name": name, "asset_path": asset.get_path_name(),
                       "asset_class": asset.get_class().get_name(), "source_sha256": expected})
    if assets[0]["asset_path"] == assets[1]["asset_path"]:
        raise RuntimeError("The two lanes collapsed into one asset")
    readback = registry_readback([asset["asset_path"] for asset in assets])
    if not readback["ok"] or readback["asset_count"] != 2:
        raise RuntimeError(f"Fresh registry readback failed: {readback}")
    payload = {"schema": "tech_connector.two_maya_blender_unreal_bevel_action_reopen.v1",
               "assets": assets, "registry_readback": readback,
               "engine_version": unreal.SystemLibrary.get_engine_version()}
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "assets": [asset["asset_path"] for asset in assets]}))


if __name__ == "__main__":
    main()
