"""Verify disposable two-mesh DCC and engine receipts without overclaiming scope."""

from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
from typing import Any


def _read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_matches(receipt: dict[str, Any]) -> bool:
    path = Path(str(receipt.get("path") or ""))
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    return (
        path.stat().st_size == receipt.get("bytes")
        and hashlib.sha256(path.read_bytes()).hexdigest() == receipt.get("sha256")
    )


def verify_two_mesh_live_proof(
    dcc_report_path: str | Path,
    unreal_report_path: str | Path,
    inspection_path: str | Path,
    unreal_project_root: str | Path,
) -> dict[str, Any]:
    """Validate live artifacts while keeping partial and continuous proof distinct."""

    errors: list[str] = []
    try:
        dcc = _read(dcc_report_path)
        unreal = _read(unreal_report_path)
        inspection = _read(inspection_path)
    except (OSError, ValueError) as exc:
        return {"verified_partial": False, "continuous_graph_proven": False,
                "demo_ready": False, "errors": [f"Unreadable receipt: {exc}"]}

    if dcc.get("schema") != "tech_connector.two_named_mesh_live_partial.v1" or not dcc.get("passed"):
        errors.append("DCC report is not a passing two-mesh partial receipt")
    if unreal.get("schema") != "tech_connector.two_mesh_unreal_import.v1" or not unreal.get("passed"):
        errors.append("Unreal import report is not passing")
    if not inspection.get("passed"):
        errors.append("Fresh Unreal inspection did not pass")
    if dcc.get("plan_stage_count") != 12:
        errors.append("Planned graph does not have 12 stages")

    names = ("Crate_A", "Barrel_B")
    lane_rows = list(dcc.get("lanes") or [])
    if sorted(str(row.get("name")) for row in lane_rows) != sorted(names):
        errors.append("DCC receipt does not contain two distinct named lanes")
    stages = list(dcc.get("stage_receipts") or [])
    if len(stages) != 8:
        errors.append("Expected eight live Maya/Blender stage receipts")
    expected_operations = (
        ("maya", "animation.export"),
        ("blender", "io.import_fbx"),
        ("blender", "pipeline.process_meshes_for_transfer"),
        ("blender", "blender.export_fbx"),
    )
    for name in names:
        actual = [(row.get("host"), row.get("operation")) for row in stages if row.get("lane") == name]
        if actual != list(expected_operations) or any(
            not (row.get("result", {}).get("ok", False)
                 or (row.get("operation") == "pipeline.process_meshes_for_transfer"
                     and row.get("result", {}).get("blender_scene") is True))
            for row in stages if row.get("lane") == name
        ):
            errors.append(f"{name}: live stage sequence or result is invalid")

    unreal_rows = {str(row.get("name")): row for row in unreal.get("assets") or []}
    inspected_rows = {str(row.get("name")): row for row in inspection.get("assets") or []}
    if set(unreal_rows) != set(names) or set(inspected_rows) != set(names):
        errors.append("Unreal receipts do not match both named lanes")
    root = Path(unreal_project_root).resolve()
    seen_asset_ids: set[str] = set()
    seen_object_paths: set[str] = set()
    seen_fbx_paths: set[str] = set()
    for lane in lane_rows:
        name = str(lane.get("name") or "")
        exports = list(lane.get("fbx") or [])
        if len(exports) != 2 or any(not _file_matches(row) for row in exports):
            errors.append(f"{name}: Maya/Blender FBX file receipt mismatch")
            continue
        if exports[0]["path"] == exports[1]["path"]:
            errors.append(f"{name}: source and edited FBXs are not distinct")
        for export in exports:
            if export["path"] in seen_fbx_paths:
                errors.append(f"{name}: FBX path was reused across lanes")
            seen_fbx_paths.add(export["path"])
        engine = dict(lane.get("engine") or {})
        asset_id = str(engine.get("asset_id") or "")
        if not asset_id or asset_id in seen_asset_ids:
            errors.append(f"{name}: Tech Connector asset ID missing or reused")
        seen_asset_ids.add(asset_id)
        if (engine.get("asset_type") != "tc.static_mesh" or not engine.get("valid")
                or not engine.get("source_matches_import")
                or not _file_matches(dict(engine.get("asset_file") or {}))
                or engine.get("asset_file", {}).get("sha256") != exports[1]["sha256"]):
            errors.append(f"{name}: Tech Connector asset readback mismatch")

        imported = unreal_rows.get(name, {})
        paths = list(imported.get("imported_paths") or [])
        registry = dict(imported.get("registry") or {})
        inspected = inspected_rows.get(name, {})
        if (str(imported.get("source_file") or "") != exports[1]["path"]
                or len(paths) != 1 or not registry.get("ok")
                or registry.get("assets") != paths or registry.get("missing")
                or inspected.get("object_path") != (paths[0] if paths else "")
                or not inspected.get("loaded") or not inspected.get("is_static_mesh")
                or inspected.get("class") != "StaticMesh"):
            errors.append(f"{name}: Unreal registry or fresh class readback mismatch")
            continue
        object_path = paths[0]
        if object_path in seen_object_paths:
            errors.append(f"{name}: Unreal object path was reused")
        seen_object_paths.add(object_path)
        package = object_path.split(".", 1)[0]
        if not package.startswith("/Game/") or ".." in Path(package).parts:
            errors.append(f"{name}: invalid Unreal package path")
            continue
        saved_asset = root / "Content" / (package[len("/Game/"):] + ".uasset")
        if not saved_asset.is_file() or saved_asset.stat().st_size <= 0:
            errors.append(f"{name}: saved Unreal .uasset is missing")

    return {
        "schema": "tech_connector.two_mesh_live_proof_verification.v1",
        "verified_partial": not errors,
        "continuous_graph_proven": False,
        "demo_ready": False,
        "asset_names": list(names),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dcc_report")
    parser.add_argument("unreal_report")
    parser.add_argument("inspection_report")
    parser.add_argument("unreal_project_root")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_two_mesh_live_proof(
        args.dcc_report, args.unreal_report, args.inspection_report,
        args.unreal_project_root,
    )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["verified_partial"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
