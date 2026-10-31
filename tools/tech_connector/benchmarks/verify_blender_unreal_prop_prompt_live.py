"""Fail-closed verification of a prompt-bound Blender-to-Unreal prop receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from tech_connector.services.action_planner_service import plan_prompt_to_action_graph


SCHEMA = "tech_connector.blender_unreal_prop_prompt.v1"
READBACK_SCHEMA = "tech_connector.blender_unreal_prop_fresh_readback.v1"
OPERATIONS = (
    "pipeline.process_meshes_for_transfer",
    "blender.export_fbx",
    "unreal_tools.asset_transfer_adapter.import_fbx_verified",
    "unreal_tools.asset_transfer_adapter.registry_readback",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def verify_blender_unreal_prop_prompt_proof(report_path: str | Path) -> dict[str, Any]:
    """Tie prompt, continuous action results, files, and fresh UE readback together."""
    path = Path(report_path).expanduser().resolve()
    report = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(report, dict) and report.get("schema") == SCHEMA
             and report.get("ok") is True, "Not a successful prop receipt")
    prompt = report.get("prompt")
    _require(isinstance(prompt, str) and prompt.strip(), "Missing custom prompt")
    _require(all(word in prompt.lower() for word in
                 ("clean names", "apply transforms", "lod0", "lod1", "collision")),
             "Prompt does not request the full prop workflow")
    plan = plan_prompt_to_action_graph(prompt, [str(Path(__file__).resolve().parents[2])])
    stages = list(plan.get("stages") or [])
    _require(plan.get("success") and plan.get("execution_ready")
             and not plan.get("gaps") and not plan.get("required_inputs")
             and tuple(stage.get("operation") for stage in stages) == OPERATIONS,
             "Prompt no longer compiles to the full prop workflow")
    recorded = [{"id": stage["id"], "host": stage["host"],
                 "operation": stage["operation"], "params": stage["params"]}
                for stage in stages]
    _require(report.get("stages") == recorded, "Receipt stages differ from prompt plan")
    process, export, imported, registry = stages
    _require(process["params"].get("clean_names") is True
             and process["params"].get("apply_transforms") is True
             and int(process["params"].get("lod_count") or 0) >= 1
             and process["params"].get("create_collision") is True
             and imported["params"].get("assemble_lods") is True,
             "LOD/collision intent was not compiled into host actions")

    execution = report.get("action_report") or {}
    statuses = execution.get("action_statuses") or {}
    _require(execution.get("status") == "completed"
             and len(statuses) == len(stages)
             and all((statuses.get(stage["id"]) or {}).get("status") == "completed"
                     for stage in stages), "Continuous action graph did not complete")
    results = []
    for stage in stages:
        raw = ((statuses[stage["id"]].get("result") or {}).get("raw_result") or {})
        _require(raw.get("ok") is True and raw.get("status") == "completed"
                 and raw.get("operation") == stage["operation"]
                 and raw.get("host") == stage["host"]
                 and isinstance(raw.get("result"), dict),
                 f"Missing successful host result for {stage['operation']}")
        results.append(raw["result"])
    prepared, exported, installed, readback = results
    _require(prepared.get("lods") and prepared.get("collision")
             and set(prepared.get("export_objects") or []) == set(exported.get("selected") or []),
             "Blender LOD/collision objects were not handed to FBX export")

    project = Path(str(report.get("project") or "")).resolve()
    fbx = Path(str(report.get("fbx_path") or "")).resolve()
    _require(project.is_file() and fbx.is_file(), "Source FBX or UE project is missing")
    _require(str(fbx) == str(Path(str(export["params"]["output_path"])).resolve())
             and str(fbx) == str(Path(str(exported.get("fbx_path") or "")).resolve())
             and str(fbx) == str(Path(str(installed.get("source_file") or "")).resolve())
             and int(report.get("fbx_bytes") or 0) == fbx.stat().st_size
             and report.get("fbx_sha256") == _sha256(fbx),
             "FBX handoff or hash differs from prompt receipt")
    destination = str(imported["params"].get("destination_path") or "")
    assets = installed.get("imported_paths") or []
    assemblies = installed.get("lod_assemblies") or []
    _require(destination.startswith("/Game/")
             and installed.get("destination_path") == destination
             and installed.get("subject") == "static_mesh"
             and len(assets) >= 2 and len(assemblies) >= 1
             and readback.get("ok") is True and not readback.get("missing")
             and readback.get("destination_path") == destination
             and set(readback.get("assets") or []) == set(assets),
             "Unreal import, LOD assembly, or registry readback is incomplete")
    assembly = assemblies[0]
    base_path = str(assembly.get("base_path") or "")
    _require(base_path in assets and assembly.get("source_path") in assets
             and int(assembly.get("lod_index") or 0) == 1
             and int(assembly.get("actual_lods") or 0) >= 2,
             "LOD1 was not attached to the imported base mesh")
    package = base_path.split(".", 1)[0]
    _require(package.startswith(destination + "/") and
             re.fullmatch(r"/Game(?:/[A-Za-z_][A-Za-z0-9_]*)+", package),
             "Imported base mesh path is invalid")
    asset_file = project.parent / "Content" / Path(*package.split("/")[2:])
    asset_file = asset_file.with_suffix(".uasset")
    _require(asset_file.is_file() and report.get("asset_bytes") == asset_file.stat().st_size
             and report.get("asset_sha256") == _sha256(asset_file),
             "Saved Unreal base asset differs from receipt")

    match = re.search(r"_v([0-9]+)$", fbx.stem)
    _require(match is not None, "Proof FBX lacks a versioned fresh-readback name")
    fresh_path = path.parent / f"blender_unreal_prop_v{match.group(1)}_fresh_readback.json"
    fresh = json.loads(fresh_path.read_text(encoding="utf-8"))
    _require(fresh.get("schema") == READBACK_SCHEMA and fresh.get("ok") is True
             and fresh.get("asset_path") == package
             and fresh.get("asset_class") == "StaticMesh"
             and int(fresh.get("lod_count") or 0) >= 2
             and int(fresh.get("convex_collision_count") or 0) >= 1
             and fresh.get("asset_sha256") == _sha256(asset_file)
             and fresh.get("fbx_sha256") == _sha256(fbx),
             "Fresh Unreal process did not confirm LOD1, collision, and exact files")
    return {
        "verified": True,
        "continuous_action_graph_proven": True,
        "asset_path": package,
        "fbx_sha256": _sha256(fbx),
        "unreal_asset_sha256": _sha256(asset_file),
        "lod_count": int(fresh["lod_count"]),
        "convex_collision_count": int(fresh["convex_collision_count"]),
        "fresh_readback_path": str(fresh_path),
    }
