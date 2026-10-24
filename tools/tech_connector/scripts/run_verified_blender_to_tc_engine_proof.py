"""Import an independently verified Blender FBX into a fresh Tech Connector project."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tech_connector.benchmarks.verify_two_mesh_action_engine_live import verify_action_engine_proof
from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.asset_operations_service import AssetOperationsService
from tech_connector.game_engine.integration.tech_connector_pipeline_adapter import import_interchange_asset


SCHEMA = "tech_connector.verified_blender_tc_engine.v1"


def verify_report(path: str | Path) -> dict:
    """Recheck the original host proof, source hash, imported bytes and engine DB."""
    report_path = Path(path).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != SCHEMA or not report.get("passed"):
        raise ValueError("Not a passing Blender-to-Tech Connector proof report")
    if report.get("tech_connector_asset", {}).get("type") != "tc.static_mesh":
        raise RuntimeError("Engine import is not a static-mesh asset")
    upstream = Path(report["upstream_proof"]).resolve()
    upstream_check = verify_action_engine_proof(
        upstream, upstream.parent / "unreal_fresh_inspection.json"
    )
    if not upstream_check.get("verified"):
        raise RuntimeError("Upstream Blender handoff proof no longer verifies")
    source = Path(report["blender_fbx"]["path"]).resolve()
    approved = {
        Path(row["path"]).resolve() for row in upstream_check["artifacts"]
        if row["name"] == report["asset_name"] and Path(row["path"]).stem.endswith("_blender")
        and Path(row["path"]).suffix.lower() == ".fbx"
    }
    if source not in approved:
        raise RuntimeError("FBX is not the selected verified Blender handoff")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != report["blender_fbx"]["sha256"]:
        raise RuntimeError("Blender FBX changed after import")
    root = Path(report["project_root"]).resolve()
    asset = Path(report["tech_connector_asset"]["path"]).resolve()
    if not asset.is_file() or not asset.is_relative_to(root):
        raise RuntimeError("Imported asset is missing or outside the project")
    if hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Engine asset bytes differ from verified Blender FBX")
    database = AssetDatabase(root / ".tech_connector" / "assets.sqlite3")
    validation = AssetOperationsService(root, database).validate_asset(
        report["tech_connector_asset"]["asset_id"]
    )
    if not validation.valid:
        raise RuntimeError("Fresh engine asset validation failed")
    return {
        "verified": True,
        "asset_id": report["tech_connector_asset"]["asset_id"],
        "asset_path": str(asset),
        "source_sha256": digest,
        "upstream_proof": str(upstream),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-proof", type=Path, required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    upstream = args.upstream_proof.resolve()
    project = args.project_root.resolve()
    destination = args.report.resolve()
    if project.exists() or destination.exists():
        raise FileExistsError("Proof project and report must be new paths")
    if destination == upstream or destination.is_relative_to(project):
        raise ValueError("Report cannot overwrite input or lie inside the generated project")
    verification = verify_action_engine_proof(
        upstream, upstream.parent / "unreal_fresh_inspection.json"
    )
    if not verification.get("verified"):
        raise RuntimeError("Upstream two-mesh action proof is not verified")
    matching = [
        row for row in verification["artifacts"]
        if row["name"] == args.asset_name and Path(row["path"]).stem.endswith("_blender")
        and Path(row["path"]).suffix.lower() == ".fbx"
    ]
    if len(matching) != 1:
        raise ValueError("Expected one verified Blender FBX for the requested asset")
    source = Path(matching[0]["path"]).resolve()
    project.mkdir(parents=True)
    imported = import_interchange_asset(str(source), str(project), folder="Assets/Imported")
    if imported.get("asset_count") != 1 or imported.get("asset_type") != "tc.static_mesh":
        raise RuntimeError("Engine import did not produce exactly one static-mesh asset")
    report = {
        "schema": SCHEMA,
        "passed": True,
        "asset_name": args.asset_name,
        "upstream_proof": str(upstream),
        "project_root": str(project),
        "blender_fbx": {"path": str(source), "sha256": matching[0]["sha256"]},
        "tech_connector_asset": {
            "asset_id": imported["asset_id"],
            "path": imported["asset_path"],
            "type": imported["asset_type"],
        },
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verify_report(destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
