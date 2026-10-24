"""Reopen the disposable Unreal project and independently validate bevel import."""

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
    receipt = Path(os.environ["TC_BEVEL_UNREAL_RESULT"]).resolve()
    output = Path(os.environ["TC_BEVEL_UNREAL_REOPEN_RESULT"]).resolve()
    if output.exists():
        raise FileExistsError(output)
    original = json.loads(receipt.read_text(encoding="utf-8"))
    if original.get("schema") != "tech_connector.blender_bevel_unreal_import.v1":
        raise ValueError("Unexpected import receipt schema")
    source = Path(original["source_file"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != original["source_sha256"]:
        raise RuntimeError("FBX source changed since import")
    path = original["static_mesh_path"]
    readback = registry_readback([path])
    asset = unreal.load_asset(path)
    if not readback["ok"] or not isinstance(asset, unreal.StaticMesh):
        raise RuntimeError(f"Saved Unreal static mesh failed fresh-process readback: {path}")
    result = {
        "schema": "tech_connector.blender_bevel_unreal_reopen.v1",
        "asset_path": asset.get_path_name(),
        "registry_readback": readback,
        "lod_count": int(asset.get_num_lods()),
        "source_sha256": original["source_sha256"],
        "engine_version": unreal.SystemLibrary.get_engine_version(),
    }
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "asset": result["asset_path"]}))


if __name__ == "__main__":
    main()
