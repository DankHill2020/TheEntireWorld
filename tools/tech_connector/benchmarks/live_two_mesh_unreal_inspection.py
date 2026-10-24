"""Fresh-process class/readback check for a disposable two-mesh Unreal proof."""

import json
import os
from pathlib import Path
import unreal


root = Path(os.environ["TECH_CONNECTOR_UNREAL_PROOF_ROOT"])
rows = []
for name in ("Crate_A", "Barrel_B"):
    object_path = f"/Game/TechConnectorProof/{name}_blender.{name}_blender"
    asset = unreal.load_asset(object_path)
    rows.append({
        "name": name,
        "object_path": object_path,
        "loaded": asset is not None,
        "class": str(asset.get_class().get_name()) if asset is not None else "",
        "is_static_mesh": isinstance(asset, unreal.StaticMesh),
    })
report = {"passed": len(rows) == 2 and all(row["is_static_mesh"] for row in rows), "assets": rows}
(root / "unreal_fresh_inspection.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
