"""Verify the first, single-host Blender prompt in a live pipeline receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


def verify_blender_single_host_prompt_proof(report_path: str | Path) -> dict:
    report_path = Path(report_path).expanduser().resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "tech_connector.live_blender_tc_prompt.v1":
        raise ValueError("Unexpected Blender live-proof schema")
    prompt = report.get("prompt")
    if (not isinstance(prompt, str)
            or classify_prompt_route(prompt).route != "pipeline_graph"
            or report.get("route") != "pipeline_graph"
            or report.get("plan_success") is not True
            or report.get("plan_execution_ready") is not True):
        raise ValueError("Blender prompt did not qualify as an executable pipeline")
    stages = report.get("stages") or []
    if len(stages) != 2 or [stage.get("operation") for stage in stages] != [
        "pipeline.process_meshes_for_transfer", "io.export_fbx",
    ]:
        raise ValueError("Blender operation sequence changed")
    first, second = stages
    first_params = first.get("params") or {}
    second_params = second.get("params") or {}
    if (first_params.get("clean_names") is not True
            or first_params.get("apply_transforms") is not True
            or int(first_params.get("lod_count") or 0) < 1
            or second_params.get("selected_only") is not True
            or (second_params.get("object_names") or {}).get("from_action") != first.get("id")):
        raise ValueError("Blender mesh preparation or export dependency changed")
    export = Path(str(second_params.get("filepath") or "")).expanduser().resolve()
    if (export.parent != report_path.parent or export.as_posix() not in prompt
            or report.get("export_exists") is not True or not export.is_file()):
        raise ValueError("Prompt export artifact is missing or out of scope")
    if (export.stat().st_size != report.get("export_bytes")
            or hashlib.sha256(export.read_bytes()).hexdigest() != report.get("export_sha256")):
        raise ValueError("Prompt export artifact changed after validation")
    results = report.get("result_summary") or {}
    if (report.get("execution_status") != "completed"
            or (report.get("status_counts") or {}).get("completed") != 2
            or not (report.get("session") or {}).get("ok")
            or any((results.get(stage.get("id")) or {}).get("status") != "succeeded"
                   or (results.get(stage.get("id")) or {}).get("ok") is not True
                   for stage in stages)):
        raise ValueError("Live Blender actions did not both complete")
    meshes = report.get("reimport_meshes") or []
    if (report.get("reimport_exit_code") != 0
            or not any(isinstance(name, str) and name.endswith("_LOD1")
                       and name[:-5] in meshes for name in meshes)):
        raise ValueError("Fresh Blender reimport did not contain base and LOD1 meshes")
    return {
        "verified": True,
        "export_path": str(export),
        "export_bytes": report["export_bytes"],
        "export_sha256": report["export_sha256"],
        "reimport_meshes": meshes,
    }
