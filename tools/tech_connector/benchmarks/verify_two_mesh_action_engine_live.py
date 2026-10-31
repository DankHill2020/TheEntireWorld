"""Validate a complete two-mesh action-engine run and fresh Unreal readback."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


_LANES = (
    ("Crate_A", (1, 2, 3, 4, 5, 6)),
    ("Barrel_B", (7, 8, 9, 10, 11, 12)),
)


def verify_action_engine_proof(report_path: str | Path, inspection_path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        inspection = json.loads(Path(inspection_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"verified": False, "errors": [f"Unreadable proof receipt: {exc}"]}
    root = Path(report_path).resolve().parent
    action = dict(report.get("action_report") or {})
    results = dict(action.get("results") or {})
    planned_actions = list(action.get("validation", {}).get("graph", {}).get("actions") or [])
    if (report.get("schema") != "tech_connector.two_mesh_action_engine_live.v1"
            or not report.get("passed") or report.get("plan_stage_count") != 12
            or action.get("status") != "completed" or len(results) != 12
            or action.get("status_counts") != {"completed": 12}):
        errors.append("Full 12-stage action-engine completion is not proven")
    expected_operations = (
        "animation.export", "io.import_fbx", "pipeline.process_meshes_for_transfer",
        "blender.export_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified",
        "unreal_tools.asset_transfer_adapter.registry_readback",
    )
    for name, numbers in _LANES:
        lane_actions = [next((row for row in planned_actions if str(row.get("id", "")).startswith(f"stage_{number:02d}_")), {})
                        for number in numbers]
        if ([row.get("args", {}).get("operation") for row in lane_actions] != list(expected_operations)
                or any(row.get("args", {}).get("asset_lane") != name for row in lane_actions)
                or lane_actions[0].get("depends_on") != []):
            errors.append(f"{name}: planned lane operations or independent root changed")
    unreal_calls = list(report.get("unreal_calls") or [])
    mode = report.get("unreal_mode")
    if mode == "isolated_commandlet_per_action":
        calls_ok = len(unreal_calls) == 4 and all(
            row.get("process_exit_code") == 0 and row.get("ok") for row in unreal_calls
        )
    elif mode == "persistent_commandlet_http":
        operations = [str(row.get("operation") or "") for row in unreal_calls]
        calls_ok = (
            report.get("unreal_process_exit_code") == 0
            and len(unreal_calls) == 4 and all(row.get("ok") for row in unreal_calls)
            and operations.count("unreal_tools.asset_transfer_adapter.import_fbx_verified") == 2
            and operations.count("unreal_tools.asset_transfer_adapter.registry_readback") == 2
        )
    else:
        calls_ok = False
    if not calls_ok:
        errors.append("Four successful Unreal dispatches are not proven")
    if not inspection.get("passed"):
        errors.append("Fresh Unreal readback did not pass")
    inspected = {str(row.get("name")): row for row in inspection.get("assets") or []}
    if set(inspected) != {name for name, _ in _LANES}:
        errors.append("Fresh readback does not identify both named meshes")
    seen_paths: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    for name, numbers in _LANES:
        rows = [results.get(next((key for key in results if key.startswith(f"stage_{number:02d}_")), ""), {})
                for number in numbers]
        if any(not row.get("ok") or row.get("execution_status") != "succeeded" for row in rows):
            errors.append(f"{name}: one or more actions did not succeed")
            continue
        outputs = [dict(row.get("raw_result", {}).get("result") or {}) for row in rows]
        source_path = Path(str(outputs[0].get("fbx_path") or ""))
        edited_path = Path(str(outputs[3].get("fbx_path") or ""))
        for path in (source_path, edited_path):
            if not path.is_file() or path.stat().st_size <= 0 or path.parent.resolve() != root:
                errors.append(f"{name}: FBX artifact missing or outside proof workspace: {path}")
                continue
            if str(path) in seen_paths:
                errors.append(f"{name}: FBX artifact path reused")
            seen_paths.add(str(path))
            artifacts.append({"name": name, "path": str(path), "bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if str(outputs[1].get("filepath")) != str(source_path):
            errors.append(f"{name}: Blender import did not consume its Maya export")
        if name not in list(outputs[2].get("export_objects") or []):
            errors.append(f"{name}: Blender processing did not retain the named mesh")
        if str(outputs[4].get("source_file")) != str(edited_path):
            errors.append(f"{name}: Unreal import did not consume its edited FBX")
        object_paths = list(outputs[4].get("imported_paths") or [])
        readback = outputs[5]
        if (len(object_paths) != 1 or object_paths[0] in seen_paths
                or not readback.get("ok") or readback.get("assets") != object_paths
                or readback.get("missing") or readback.get("asset_count") != 1):
            errors.append(f"{name}: Unreal registry readback is incomplete or reused")
            continue
        object_path = object_paths[0]
        seen_paths.add(object_path)
        inspected_row = inspected.get(name, {})
        if (inspected_row.get("object_path") != object_path or not inspected_row.get("loaded")
                or inspected_row.get("class") != "StaticMesh" or not inspected_row.get("is_static_mesh")):
            errors.append(f"{name}: fresh Unreal class inspection did not match")
        package = object_path.split(".", 1)[0]
        if not package.startswith("/Game/") or ".." in Path(package).parts:
            errors.append(f"{name}: invalid Unreal package path")
            continue
        saved = root / "UnrealActionProof" / "Content" / (package[len("/Game/"):] + ".uasset")
        if not saved.is_file() or saved.stat().st_size <= 0:
            errors.append(f"{name}: saved Unreal asset is missing")
        else:
            artifacts.append({"name": name, "path": str(saved), "bytes": saved.stat().st_size,
                              "sha256": hashlib.sha256(saved.read_bytes()).hexdigest()})
    return {
        "schema": "tech_connector.two_mesh_action_engine_verification.v1",
        "verified": not errors,
        "continuous_action_graph_proven": not errors,
        "scope": "one custom prompt, two named static meshes, Maya→Blender→Unreal",
        "demo_ready": False,
        "elapsed_seconds": report.get("elapsed_seconds"),
        "artifacts": artifacts,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("inspection")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_action_engine_proof(args.report, args.inspection)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
