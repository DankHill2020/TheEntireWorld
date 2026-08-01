from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from tech_connector.models.constants import active_project_root, temp_output_path

SCRIPT_ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from reasoning_runtime.engine.request_context import RequestContext
from tech_connector.services.prompt.prompt_dispatch_service import PromptDispatchService
from tech_connector.services.prompt.prompt_execution_context_service import (
    build_prompt_execution_context,
    validate_prompt_understanding,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.prompt.prompt_stage_quality_service import audit_prompt_stage_quality


PROMPTS: list[dict[str, Any]] = [
    {
        "id": "maya_rig_tool",
        "host": "maya",
        "expected_routes": ["target_discovery"],
        "prompt": (
            "In Maya, build a production rigging utility: find existing skinning and HIK functions, "
            "create a PySide tool that binds the selected mesh to selected joints, adds/removes influences, "
            "validates selection and namespaces, logs every operation, and includes focused tests."
        ),
    },
    {
        "id": "maya_to_unreal_anim_pipeline",
        "host": "maya",
        "expected_routes": ["pipeline_graph"],
        "prompt": (
            "Create a pipeline from prompt: in Maya export selected Manny joints and animation to "
            "C:/tmp/tc_manny_climb.fbx, validate frame range and root motion, then in Unreal import it into "
            "/Game/Characters/Manny/Animations, retarget if needed, validate skeleton compatibility, and report assets."
        ),
    },
    {
        "id": "blender_to_unreal_prop_pipeline",
        "host": "blender",
        "expected_routes": ["pipeline_graph", "dcc_execute", "target_discovery"],
        "prompt": (
            "Build a Blender to Unreal prop pipeline: clean selected mesh names, apply transforms, generate LOD0/LOD1, "
            "export FBX to C:/tmp/tc_prop.fbx, then import into Unreal /Game/Props/Test, create material slots, "
            "set collision, save assets, and produce validation output."
        ),
    },
    {
        "id": "blender_scene_tool",
        "host": "blender",
        "expected_routes": ["target_discovery", "dcc_execute"],
        "prompt": (
            "In Blender create a reusable scene cleanup operator and small UI panel: find duplicate material slots, "
            "rename selected objects to studio convention, apply transforms, pack external textures, and show a dry-run preview."
        ),
    },
    {
        "id": "unreal_abp_crawl",
        "host": "unreal",
        "expected_routes": ["unreal_capability"],
        "prompt": (
            "In Unreal, make Manny crawl in ABP_Combat: inspect the AnimBlueprint, add prone idle and crawl forward/back/strafe "
            "states, synthesize transition rules from crouch using bWantsToCrawl and CrawlInputVector, wire the state machine "
            "to output pose, compile/save, and validate with readback."
        ),
    },
    {
        "id": "unreal_network_inventory",
        "host": "unreal",
        "expected_routes": ["target_discovery", "unreal_capability"],
        "prompt": (
            "In Unreal implement a networked pickup and inventory flow: overlap detection, server authority, client request RPC, "
            "replicated inventory array, OnRep HUD notification, save/load hook, rollback journal, and two-client PIE validation."
        ),
    },
]


def _bridge_status() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for host, bridge in (
        ("maya", MayaBridge()),
        ("blender", BlenderBridge()),
        ("unreal", UnrealBridge()),
    ):
        started = perf_counter()
        row: dict[str, Any] = {"port": None, "connected": False, "detail": ""}
        try:
            row["port"] = bridge.find_port() if hasattr(bridge, "find_port") else None
            if host == "unreal":
                health = bridge.health_check(timeout=1.5)
                row["connected"] = bool(health.get("connected"))
                row["detail"] = health.get("error") or health.get("loaded_level") or ""
                row["health"] = health
            elif row["port"]:
                ok, out = bridge.execute("print('TECH_CONNECTOR_AUDIT_PING')", timeout=2)
                row["connected"] = bool(ok)
                row["detail"] = str(out)
            else:
                row["detail"] = f"No {host} bridge detected."
        except Exception as exc:
            row["detail"] = str(exc)
        row["elapsed_ms"] = round((perf_counter() - started) * 1000.0, 2)
        rows[host] = row
    return rows


def _compact_decision(decision: Any) -> dict[str, Any]:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    return {
        "route": data.get("route"),
        "provider": data.get("provider"),
        "host": data.get("host"),
        "intent_category": data.get("intent_category"),
        "execution_route": data.get("execution_route"),
        "requires_confirmation": data.get("requires_confirmation"),
        "requires_dcc_connection": data.get("requires_dcc_connection"),
        "mutation_scope": data.get("mutation_scope"),
        "target_identifier": data.get("target_identifier"),
        "callable_name": data.get("callable_name"),
        "required_context": data.get("required_context"),
        "reasons": data.get("reasons"),
        "operations": data.get("operations"),
        "task_graph": data.get("task_graph"),
        "capability_gap_plan": data.get("capability_gap_plan"),
    }


def _audit_prompt(case: dict[str, Any], project_roots: list[str], availability: dict[str, Any]) -> dict[str, Any]:
    prompt = str(case["prompt"])
    started = perf_counter()
    timings: dict[str, float] = {}
    phase_started = perf_counter()
    context = build_prompt_execution_context(
        prompt,
        host_hint=str(case.get("host") or ""),
        decision_facts={
            "project_roots": project_roots,
            "settings": {"ai_work_memory_enabled": False},
            "capability_availability": {"hosts": availability},
        },
    )
    timings["context_build_ms"] = round((perf_counter() - phase_started) * 1000.0, 2)
    phase_started = perf_counter()
    validation = validate_prompt_understanding(context)
    timings["understanding_validation_ms"] = round((perf_counter() - phase_started) * 1000.0, 2)
    phase_started = perf_counter()
    decision = classify_prompt_route(prompt, project_roots=project_roots, execution_context=context)
    timings["route_classification_ms"] = round((perf_counter() - phase_started) * 1000.0, 2)
    decision_data = decision.to_dict()
    decision_data.setdefault("capability_availability", {"hosts": availability})
    context.attach_execution_decision(decision_data)
    phase_started = perf_counter()
    dispatch_result = PromptDispatchService().dispatch(
        decision_data,
        RequestContext(
            text=prompt,
            project_roots=tuple(project_roots),
            extras={
                "prompt_route_decision": decision_data,
                "capability_availability": {"hosts": availability},
                "settings": {"ai_work_memory_enabled": False},
            },
        ),
        emit=lambda _event: None,
    )
    timings["dispatch_ms"] = round((perf_counter() - phase_started) * 1000.0, 2)
    phase_started = perf_counter()
    quality = audit_prompt_stage_quality(
        prompt,
        project_roots=project_roots,
        host_hint=str(case.get("host") or ""),
        expected_routes=case.get("expected_routes") or [],
        require_quality_bar=bool(re.search(r"\b(tool|ui|user interface|panel|window|widget|operator)\b", prompt, re.IGNORECASE)),
        require_plan_match=True,
    )
    timings["stage_quality_ms"] = round((perf_counter() - phase_started) * 1000.0, 2)
    timings["total_ms"] = round((perf_counter() - started) * 1000.0, 2)
    planning_result = dict(context.planning_result or {})
    return {
        "id": case["id"],
        "host_hint": case.get("host") or "",
        "prompt": prompt,
        "elapsed_ms": timings["total_ms"],
        "timings": timings,
        "requirement_fulfillment": list(planning_result.get("requirement_fulfillment") or []),
        "operation_status": list(planning_result.get("operation_status") or []),
        "generated_artifacts": list(planning_result.get("generated_artifacts") or []),
        "validation_evidence": list(planning_result.get("validation_evidence") or []),
        "context": {
            "normalized_prompt": context.normalized_prompt,
            "planning_result": context.planning_result,
            "semantic_execution_contract": context.semantic_execution_contract,
            "task_graph": context.task_graph,
        },
        "understanding_validation": validation.to_dict(),
        "decision": _compact_decision(decision),
        "dispatch": {
            "action": dispatch_result.action,
            "result_type": dispatch_result.result_type,
            "label": dispatch_result.label,
            "text": dispatch_result.text,
            "metadata": dispatch_result.metadata,
        },
        "stage_quality": quality.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run complex Maya/Blender/Unreal prompt planning audit.")
    parser.add_argument(
        "--project-root",
        action="append",
        default=[str(active_project_root())],
    )
    parser.add_argument(
        "--output",
        default=str(temp_output_path("complex_dcc_prompt_audit.json", subdir="reports")),
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="Also print the full JSON report to stdout.")
    args = parser.parse_args()

    cases = PROMPTS
    if args.case:
        selected = set(args.case)
        cases = [case for case in cases if case["id"] in selected]

    bridge_status = _bridge_status()
    availability = {
        host: {
            "connected": bool(row.get("connected")),
            "status": "green" if row.get("connected") else "red",
            "light": "green" if row.get("connected") else "red",
            "detail": row.get("detail") or "",
            "port": row.get("port"),
        }
        for host, row in bridge_status.items()
    }
    report = {
        "project_roots": args.project_root,
        "bridge_status": bridge_status,
        "availability": {"hosts": availability},
        "cases": [_audit_prompt(case, args.project_root, availability) for case in cases],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Wrote full audit report: {args.output}")
        print("Bridge availability:")
        for host, row in availability.items():
            print(f"- {host}: {row['status']} port={row.get('port')} detail={row.get('detail')}")
        print("Cases:")
        for row in report["cases"]:
            decision = row.get("decision") or {}
            dispatch = row.get("dispatch") or {}
            quality = row.get("stage_quality") or {}
            print(
                f"- {row['id']}: route={decision.get('route')} host={decision.get('host')} "
                f"dispatch={dispatch.get('action')}/{dispatch.get('result_type')} "
                f"quality={quality.get('score')} ok={quality.get('ok')} elapsed_ms={row.get('elapsed_ms')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
