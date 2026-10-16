from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tech_connector.game_engine.integration.pipeline_execution_preflight_service import (
    resolve_pipeline_session_ports,
)
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import (
    execute_pipeline_operation,
)
from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.asset_operations_service import AssetOperationsService


CALLABLES = {
    "maya": [
        "maya_tools.Rigging.validation_proxy.create_rigged_proxy",
        "maya_tools.Rigging.validation_proxy.inspect_rigged_proxy",
        "maya_tools.Animation.anim_export.bridge_export.export_fbx",
    ],
    "blender": [
        "blender_tools.io.import_fbx",
        "blender_tools.pipeline_transfer.process_meshes_for_transfer",
        "blender_tools.validation.inspect_generalist_asset",
        "blender_tools.io.export_fbx",
    ],
}


def _run(host: str, operation: str, callable_name: str, params: dict, ports: dict[str, int]) -> dict:
    started = time.perf_counter()
    result = execute_pipeline_operation(
        host,
        operation,
        callable_name,
        params,
        session_port=ports.get(host),
        timeout_seconds=120.0,
    )
    return {
        "host": host,
        "operation": operation,
        "callable": callable_name,
        "params": params,
        "result": result,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a disposable live Maya-to-Blender FBX proof.")
    parser.add_argument("--maya-port", type=int, default=7001)
    parser.add_argument("--blender-port", type=int, default=7021)
    parser.add_argument("--output-dir", default=str(Path(tempfile.gettempdir()) / "tc_live_e2e"))
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = f"TC_E2E_{stamp}"
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    maya_fbx = output_dir / f"{prefix}_maya.fbx"
    blender_fbx = output_dir / f"{prefix}_blender.fbx"
    tc_project = output_dir / f"{prefix}_tc_project"
    report_path = Path(args.report).resolve() if args.report else output_dir / f"{prefix}_report.json"

    ports = resolve_pipeline_session_ports(
        ["maya", "blender"],
        session_ports={"maya": args.maya_port, "blender": args.blender_port},
        callables_by_host=CALLABLES,
        timeout_seconds=5.0,
    )
    steps: list[dict] = []
    steps.append(_run(
        "maya", "pipeline.create_rigged_proxy", CALLABLES["maya"][0],
        {"name_prefix": prefix, "start_frame": 1, "end_frame": 24, "travel_distance": 25.0}, ports,
    ))
    maya_inspection = _run(
        "maya", "pipeline.inspect_rigged_proxy", CALLABLES["maya"][1],
        {"name_prefix": prefix, "start_frame": 1, "end_frame": 24}, ports,
    )
    steps.append(maya_inspection)
    maya_checks = dict(maya_inspection["result"].get("parity_checks") or {})
    if not maya_checks or not all(maya_checks.values()):
        raise RuntimeError(f"Maya proxy parity failed: {maya_checks}")

    steps.append(_run(
        "maya", "animation.export", CALLABLES["maya"][2],
        {
            "export_path": str(maya_fbx), "start_frame": 1, "end_frame": 24,
            "selected_only": True, "nodes": [f"{prefix}_Mesh", f"{prefix}_Root"],
        }, ports,
    ))
    if not maya_fbx.is_file() or maya_fbx.stat().st_size <= 0:
        raise RuntimeError(f"Maya FBX was not created: {maya_fbx}")

    blender_import = _run(
        "blender", "io.import_fbx", CALLABLES["blender"][0],
        {"filepath": str(maya_fbx), "use_image_search": True}, ports,
    )
    steps.append(blender_import)
    imported_objects = list(blender_import["result"].get("objects") or [])
    if f"{prefix}_Mesh" not in imported_objects:
        raise RuntimeError(f"Blender did not report the transferred mesh: {imported_objects}")

    blender_process = _run(
        "blender", "pipeline.process_meshes_for_transfer", CALLABLES["blender"][1],
        {
            "objects": [f"{prefix}_Mesh"], "clean_names": True,
            "apply_transforms": True, "lod_count": 1,
            "ensure_material_slots": True, "create_collision": True,
        }, ports,
    )
    steps.append(blender_process)
    process_result = blender_process["result"]
    if not process_result.get("lods") or not process_result.get("collision"):
        raise RuntimeError(f"Blender LOD/collision processing did not complete: {process_result}")

    blender_inspection = _run(
        "blender", "workflow.inspect_generalist_asset", CALLABLES["blender"][2],
        {
            "object_name": f"{prefix}_Mesh", "material_name": f"{prefix}_Material",
            "start_frame": 1, "end_frame": 24,
        }, ports,
    )
    steps.append(blender_inspection)
    blender_checks = dict(blender_inspection["result"].get("parity_checks") or {})
    for required_check in ("topology", "UV and materials", "animation range"):
        if not blender_checks.get(required_check):
            raise RuntimeError(f"Blender parity failed `{required_check}`: {blender_checks}")

    export_objects = list(dict.fromkeys(
        imported_objects
        + list(process_result.get("lods") or [])
        + list(process_result.get("collision") or [])
    ))
    steps.append(_run(
        "blender", "io.export_fbx", CALLABLES["blender"][3],
        {
            "filepath": str(blender_fbx),
            "selected_only": True,
            "object_names": export_objects,
        },
        ports,
    ))
    if not blender_fbx.is_file() or blender_fbx.stat().st_size <= 0:
        raise RuntimeError(f"Blender FBX was not created: {blender_fbx}")

    tc_project.mkdir(parents=True, exist_ok=True)
    tc_import = _run(
        "tech_connector",
        "asset.import_interchange",
        "tech_connector.game_engine.integration.tech_connector_pipeline_adapter.import_interchange_asset",
        {
            "source_file": str(blender_fbx),
            "project_root": str(tc_project),
            "folder": "Assets/Imported",
        },
        ports,
    )
    steps.append(tc_import)
    tc_result = tc_import["result"]
    imported_asset_path = Path(str(tc_result.get("asset_path") or ""))
    if tc_result.get("asset_count") != 1 or not imported_asset_path.is_file():
        raise RuntimeError(f"Tech Connector engine import failed readback: {tc_result}")
    database = AssetDatabase(tc_project / ".tech_connector" / "assets.sqlite3")
    validation = AssetOperationsService(tc_project, database).validate_asset(str(tc_result["asset_id"]))
    if not validation.valid:
        raise RuntimeError(f"Tech Connector engine validation failed: {validation.issues}")

    report = {
        "schema": "tech_connector.live_maya_blender_e2e.v1",
        "passed": True,
        "prefix": prefix,
        "session_ports": ports,
        "maya_fbx": {"path": str(maya_fbx), "bytes": maya_fbx.stat().st_size},
        "blender_fbx": {"path": str(blender_fbx), "bytes": blender_fbx.stat().st_size},
        "tech_connector_project": str(tc_project),
        "tech_connector_asset": {
            "asset_id": str(tc_result["asset_id"]),
            "asset_path": str(imported_asset_path),
            "asset_type": str(tc_result["asset_type"]),
            "valid": validation.valid,
            "issues": [issue.__dict__.copy() for issue in validation.issues],
        },
        "maya_parity_checks": maya_checks,
        "blender_parity_checks": blender_checks,
        "imported_objects": imported_objects,
        "exported_objects": export_objects,
        "steps": steps,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": True,
        "prefix": prefix,
        "session_ports": ports,
        "maya_fbx": report["maya_fbx"],
        "blender_fbx": report["blender_fbx"],
        "tech_connector_asset": report["tech_connector_asset"],
        "maya_parity_checks": maya_checks,
        "blender_parity_checks": blender_checks,
        "imported_objects": imported_objects,
        "exported_objects": export_objects,
        "report_path": str(report_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
