"""Verify a continuous, prompt-bound two-mesh Blender-to-Unreal handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tech_connector.services.action_planner_service import plan_prompt_to_action_graph


OPERATIONS_PER_LANE = (
    "blender.export_fbx",
    "unreal_tools.asset_transfer_adapter.import_fbx_verified",
    "unreal_tools.asset_transfer_adapter.registry_readback",
)


def _require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_named_props(report_path: str | Path, *, names: tuple[str, ...], label: str) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    report = json.loads(path.read_text(encoding="utf-8"))
    schema = f"tech_connector.blender_unreal_{label}_prompt.v1"
    fresh_schema = f"tech_connector.blender_unreal_{label}_fresh_readback.v1"
    _require(isinstance(report, dict) and report.get("schema") == schema
             and report.get("ok") is True, "Not a successful named-mesh receipt")
    prompt = report.get("prompt")
    _require(isinstance(prompt, str) and all(name in prompt for name in names),
             "Prompt lacks the named meshes")
    plan = plan_prompt_to_action_graph(prompt, [str(Path(__file__).resolve().parents[2])])
    stages = list(plan.get("stages") or [])
    _require(plan.get("success") and plan.get("execution_ready")
             and not plan.get("gaps") and not plan.get("required_inputs")
             and tuple(stage.get("operation") for stage in stages) == OPERATIONS_PER_LANE * len(names)
             and tuple(stage.get("asset_lane") for stage in stages) == tuple(
                 name for name in names for _ in range(3)
             ), "Prompt no longer compiles to independent static-mesh lanes")
    recorded = [{"id": stage["id"], "host": stage["host"],
                 "operation": stage["operation"], "asset_lane": stage["asset_lane"],
                 "params": stage["params"]} for stage in stages]
    _require(report.get("stages") == recorded, "Receipt stages differ from prompt plan")
    execution = report.get("action_report") or {}
    statuses = execution.get("action_statuses") or {}
    _require(execution.get("status") == "completed" and len(statuses) == len(names) * 3
             and all((statuses.get(stage["id"]) or {}).get("status") == "completed"
                     for stage in stages), "Continuous action graph did not complete")
    project = Path(str(report.get("project") or "")).resolve()
    _require(project.is_file(), "Unreal project is missing")
    destination = f"/Game/TCProbe/{'TwoPropsV1' if len(names) == 2 else 'ThreePropsV1'}"
    fresh_path = path.parent / f"{label}_fresh_readback.json"
    fresh = json.loads(fresh_path.read_text(encoding="utf-8"))
    _require(fresh.get("schema") == fresh_schema and fresh.get("ok") is True,
             "Fresh Unreal process did not confirm all meshes")
    rows = {}
    for index, name in enumerate(names):
        export, imported, registry = stages[index * 3:index * 3 + 3]
        raw = []
        for stage in (export, imported, registry):
            result = ((statuses[stage["id"]].get("result") or {}).get("raw_result") or {})
            _require(result.get("ok") is True and result.get("status") == "completed"
                     and result.get("operation") == stage["operation"]
                     and result.get("host") == stage["host"]
                     and isinstance(result.get("result"), dict),
                     f"Incomplete live action for {name}")
            raw.append(result["result"])
        exported, installed, readback = raw
        fbx_record = (report.get("fbx") or {}).get(name) or {}
        asset_record = (report.get("uasset") or {}).get(name) or {}
        fbx = Path(str(fbx_record.get("path") or "")).resolve()
        asset = Path(str(asset_record.get("path") or "")).resolve()
        _require(fbx.is_file() and asset.is_file()
                 and fbx.name == f"{name}.fbx" and asset.name == f"{name}.uasset"
                 and fbx_record.get("sha256") == _sha(fbx)
                 and asset_record.get("sha256") == _sha(asset)
                 and fbx_record.get("bytes") == fbx.stat().st_size
                 and asset_record.get("bytes") == asset.stat().st_size,
                 f"{name} source or saved asset is missing or changed")
        expected_asset = project.parent / "Content" / "TCProbe" / destination.rsplit("/", 1)[-1] / f"{name}.uasset"
        object_path = f"{destination}/{name}.{name}"
        _require(asset == expected_asset.resolve()
                 and str(fbx) == str(Path(str(export["params"].get("output_path") or "")).resolve())
                 and str(fbx) == str(Path(str(exported.get("fbx_path") or "")).resolve())
                 and str(fbx) == str(Path(str(installed.get("source_file") or "")).resolve())
                 and name in (exported.get("selected") or [])
                 and installed.get("destination_path") == destination
                 and installed.get("subject") == "static_mesh"
                 and installed.get("imported_paths") == [object_path]
                 and readback.get("ok") is True and not readback.get("missing")
                 and readback.get("assets") == [object_path],
                 f"{name} handoff, import, or registry readback differs from prompt")
        fresh_row = (fresh.get("assets") or {}).get(name) or {}
        _require(fresh_row.get("ok") is True
                 and fresh_row.get("path") == f"{destination}/{name}"
                 and fresh_row.get("class") == "StaticMesh"
                 and int(fresh_row.get("vertex_count") or 0) >= 8
                 and fresh_row.get("asset_sha256") == _sha(asset)
                 and fresh_row.get("fbx_sha256") == _sha(fbx),
                 f"Fresh Unreal process did not reopen exact {name} asset")
        rows[name] = {
            "fbx_sha256": _sha(fbx), "unreal_asset_sha256": _sha(asset),
            "vertex_count": int(fresh_row["vertex_count"]),
        }
    _require(len({row["vertex_count"] for row in rows.values()}) == len(names),
             "Distinct named meshes have indistinguishable geometry counts")
    return {"verified": True, "continuous_action_graph_proven": True,
            "asset_names": list(names), "assets": rows,
            "fresh_readback_path": str(fresh_path)}


def verify_blender_unreal_two_props_prompt_proof(report_path: str | Path) -> dict[str, Any]:
    return _verify_named_props(report_path, names=("Crate_A", "Barrel_B"), label="two_props")


def verify_blender_unreal_three_props_prompt_proof(report_path: str | Path) -> dict[str, Any]:
    return _verify_named_props(report_path, names=("Crate_A", "Barrel_B", "Cone_C"), label="three_props")
