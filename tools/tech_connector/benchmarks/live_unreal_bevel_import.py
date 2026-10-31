"""Import the Blender bevel proof FBX into a disposable Unreal project."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import unreal


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from unreal_tools.asset_transfer_adapter import import_fbx_verified, registry_readback  # noqa: E402


def main() -> None:
    source = Path(os.environ["TC_BEVEL_SOURCE_FBX"]).resolve()
    result = Path(os.environ["TC_BEVEL_UNREAL_RESULT"]).resolve()
    destination = str(os.environ.get("TC_BEVEL_UNREAL_DESTINATION") or "/Game/TCProbe/BevelGeneratedV1")
    if not destination.startswith("/Game/TCProbe/"):
        raise ValueError("Proof destination must stay under the disposable TCProbe folder")
    if result.exists():
        raise FileExistsError(f"Refusing to overwrite Unreal proof receipt: {result}")
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(source)
    asset = f"{destination}/{source.stem}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset):
        raise FileExistsError(f"Refusing to overwrite Unreal asset: {asset}")

    imported = import_fbx_verified(
        str(source), destination_path=destination,
        subject="static_mesh", replace_existing=False, save=True,
    )
    readback = registry_readback(imported["imported_paths"])
    if not readback["ok"]:
        raise RuntimeError(f"Unreal registry readback failed: {readback}")
    loaded = unreal.load_asset(imported["asset_path"])
    if not isinstance(loaded, unreal.StaticMesh):
        raise RuntimeError(f"Imported asset is not a StaticMesh: {imported}")
    result.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "tech_connector.blender_bevel_unreal_import.v1",
        "source_file": str(source),
        "source_bytes": source.stat().st_size,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "imported": imported,
        "registry_readback": readback,
        "static_mesh_path": loaded.get_path_name(),
        "lod_count": int(loaded.get_num_lods()),
        "engine_version": unreal.SystemLibrary.get_engine_version(),
    }
    result.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "result": str(result), "asset": payload["static_mesh_path"]}))


if __name__ == "__main__":
    main()
