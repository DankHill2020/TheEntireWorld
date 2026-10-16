from __future__ import annotations

"""Repeatable planning qualification for developer-facing demo prompts."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
from typing import Any

from reasoning_runtime.action.action_graph_service import validate_action_graph
from tech_connector.game_engine.integration.pipeline_execution_preflight_service import (
    preflight_pipeline_execution,
)
from tech_connector.services.action_planner_service import (
    plan_prompt_to_action_graph,
    workflow_plan_from_action_graph,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph


DEVELOPER_PROMPT_DEMO_SCHEMA = "tech_connector.developer_prompt_demo_qualification.v1"


@dataclass(frozen=True)
class DeveloperPromptCase:
    case_id: str
    category: str
    prompt: str
    expected_routes: tuple[str, ...]
    pipeline: bool = False
    expected_hosts: tuple[str, ...] = ()
    expected_operations: tuple[str, ...] = ()
    expected_success: bool = True
    expected_gap_kind: str = ""
    expected_explicit_functions: int = 0
    expected_result_type: str = ""
    expected_result_terms: tuple[str, ...] = ()
    forbidden_result_terms: tuple[str, ...] = ()


DEVELOPER_PROMPT_CASES: tuple[DeveloperPromptCase, ...] = (
    DeveloperPromptCase(
        "explain_qualified_maya_function", "code_understanding",
        "@maya_tools.Rigging.create_rig.rig_arm_module what does this function do and how do I use it?",
        ("project_search",),
        expected_result_type="symbol_inspection_direct",
        expected_result_terms=(
            "Signature: `rig_arm_module(side, body_joint_map, parent_ctrl=None)`",
            "Behavior from source:", "Usage:", "Rigs the Arm",
        ),
        forbidden_result_terms=("Matching indexed functions",),
    ),
    DeveloperPromptCase(
        "find_callers", "code_navigation",
        "Find all callers of build_project_edit_agent_request and explain the execution flow.",
        ("project_search",),
        expected_result_type="exact_symbol_callers_direct",
        expected_result_terms=(
            "build_project_edit_agent_request(prompt, *, active_path=None, limit=8)",
            "project_edit_workflow_runner_planning.py:68",
            "test_code_agent_prompt_smoke_suite.py:127",
        ),
        forbidden_result_terms=("detect_editor_intent", "\\dist\\"),
    ),
    DeveloperPromptCase(
        "maya_tool_authoring", "dcc_tool_development",
        "Find existing Maya rigging functions and create a PySide tool for skin binding with tests.",
        ("target_discovery",),
    ),
    DeveloperPromptCase(
        "maya_live_query", "dcc_query",
        "List the selected joints in Maya without changing the scene.",
        ("dcc_query",),
    ),
    DeveloperPromptCase(
        "unreal_gameplay_feature", "gameplay_development",
        "In Unreal add a reusable stamina system for sprinting, dodging, regeneration, and HUD updates.",
        ("target_discovery",),
    ),
    DeveloperPromptCase(
        "unreal_animation_blueprint", "animation_systems",
        "Make crawling locomotion in the Manny Animation Blueprint with prone idle, directional crawl, and crouch transitions.",
        ("unreal_capability", "target_discovery"),
    ),
    DeveloperPromptCase(
        "read_only_architecture_review", "code_review",
        "Review the Unreal graph mutation planner for performance risks and line-level evidence, but do not edit files.",
        ("project_search",),
    ),
    DeveloperPromptCase(
        "maya_to_unreal_animation", "pipeline_generation",
        "Export selected animation from Maya to C:/tmp/demo_anim.fbx and import it into Unreal using skeleton /Game/Characters/SK_Demo.",
        ("pipeline_graph", "action_graph"), True,
        ("maya", "unreal"),
        ("animation.export", "unreal_tools.asset_transfer_adapter.import_fbx_verified"),
    ),
    DeveloperPromptCase(
        "blender_to_unreal_prop", "pipeline_generation",
        "Build a Blender to Unreal prop pipeline: clean names, apply transforms, generate LOD0 and LOD1, export to C:/tmp/demo_prop.fbx, import into /Game/Demo/Props, create collision, save, and validate registry readback.",
        ("pipeline_graph", "action_graph"), True,
        ("blender", "unreal"),
        ("pipeline.process_meshes_for_transfer", "unreal_tools.asset_transfer_adapter.registry_readback"),
    ),
    DeveloperPromptCase(
        "maya_blender_unreal_character", "pipeline_generation",
        "Create a Maya to Blender to Unreal pipeline: export a rigged animated proxy to C:/tmp/demo_maya.fbx, clean it in Blender and export C:/tmp/demo_blender.fbx, then import into /Game/Demo/Characters using skeleton /Game/Characters/SK_Demo and report assets.",
        ("pipeline_graph", "action_graph"), True,
        ("maya", "blender", "unreal"),
        ("animation.export", "io.import_fbx", "blender.export_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified"),
    ),
    DeveloperPromptCase(
        "motionbuilder_blender_unreal_mocap", "pipeline_generation",
        "Export mocap animation from MotionBuilder to Blender, clean and bake it, export FBX, then import into Unreal using skeleton /Game/Characters/SK_Demo and validate compatibility.",
        ("pipeline_graph", "action_graph"), True,
        ("motionbuilder", "blender", "unreal"),
        ("io.export_fbx", "io.import_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified"),
    ),
    DeveloperPromptCase(
        "maya_motionbuilder_unreal_retarget", "pipeline_generation",
        "Export animation from Maya, open it in MotionBuilder for retargeting, export FBX, then import into Unreal using skeleton /Game/Characters/SK_Demo.",
        ("pipeline_graph", "action_graph"), True,
        ("maya", "motionbuilder", "unreal"),
        ("animation.export", "io.import_fbx", "io.export_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified"),
    ),
    DeveloperPromptCase(
        "blender_to_tc_engine", "pipeline_generation",
        "Export a static mesh from Blender into the Tech Connector engine project at C:/tmp/TC_Demo_Project.",
        ("pipeline_graph", "action_graph"), True,
        ("blender", "tech_connector"),
        ("io.export_fbx", "asset.import_interchange"),
    ),
    DeveloperPromptCase(
        "max_to_unreal", "pipeline_generation",
        "Export a static mesh from 3ds Max using 3dsmax.io.export and import it into Unreal /Game/Demo/Max, then validate registry readback.",
        ("pipeline_graph", "action_graph"), True,
        ("3dsmax", "unreal"),
        ("io.export", "unreal_tools.asset_transfer_adapter.import_fbx_verified"),
    ),
    DeveloperPromptCase(
        "explicit_function_sequence", "pipeline_generation",
        "Transfer animation from Maya through Blender to Unreal using skeleton /Game/Characters/SK_Demo. Functions: maya.scene.ls, maya.animation.export, blender.io.import_fbx, blender.pipeline.process_meshes_for_transfer, blender.blender.export_fbx, unreal_tools.asset_transfer_adapter.import_fbx_verified, unreal_tools.asset_transfer_adapter.registry_readback.",
        ("pipeline_graph", "action_graph"), True,
        ("maya", "blender", "unreal"),
        ("scene.ls", "animation.export", "io.import_fbx", "pipeline.process_meshes_for_transfer", "blender.export_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified", "unreal_tools.asset_transfer_adapter.registry_readback"),
        expected_explicit_functions=7,
    ),
    DeveloperPromptCase(
        "unknown_explicit_function", "safe_failure",
        "Export a mesh from Maya to Unreal. Functions: maya.animation.export, unreal.magic_import_everything.",
        ("pipeline_graph", "action_graph"), True,
        ("maya", "unreal"), expected_success=False,
        expected_gap_kind="unknown_requested_function",
    ),
    DeveloperPromptCase(
        "unsupported_houdini_usd_edge", "safe_failure",
        "Export a static mesh from Houdini as USD and import it into Unreal.",
        ("pipeline_graph", "action_graph"), True,
        ("houdini", "unreal"), expected_success=False,
        expected_gap_kind="missing_transfer_edge",
    ),
)


def _operation_sequence(plan: dict[str, Any]) -> list[str]:
    return [
        str((action.get("args") or {}).get("operation") or "")
        for action in plan.get("actions") or []
        if str((action.get("args") or {}).get("operation") or "")
    ]


def _ordered_subsequence(expected: tuple[str, ...], actual: list[str]) -> bool:
    cursor = 0
    for value in actual:
        if cursor < len(expected) and value == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def _load_runtime_evidence(paths: tuple[str | Path, ...]) -> dict[str, dict[str, Any]]:
    """Accept only complete, artifact-backed reports for matching demo cases."""

    evidence: dict[str, dict[str, Any]] = {}
    for value in paths:
        path = Path(value).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if payload.get("schema") != "tech_connector.live_maya_blender_e2e.v1" or not payload.get("passed"):
            continue
        tc_asset = dict(payload.get("tech_connector_asset") or {})
        blender_fbx = dict(payload.get("blender_fbx") or {})
        maya_checks = dict(payload.get("maya_parity_checks") or {})
        blender_checks = dict(payload.get("blender_parity_checks") or {})
        required = bool(
            tc_asset.get("valid")
            and Path(str(tc_asset.get("asset_path") or "")).is_file()
            and Path(str(blender_fbx.get("path") or "")).is_file()
            and maya_checks
            and all(maya_checks.values())
            and blender_checks
            and all(blender_checks.values())
        )
        if required:
            evidence["blender_to_tc_engine"] = {
                "schema": payload["schema"],
                "report_path": str(path),
                "asset_id": str(tc_asset.get("asset_id") or ""),
                "asset_path": str(tc_asset.get("asset_path") or ""),
            }
    return evidence


def qualify_developer_demo_prompts(
    project_root: str | Path,
    *,
    output_path: str | Path | None = None,
    cases: tuple[DeveloperPromptCase, ...] = DEVELOPER_PROMPT_CASES,
    runtime_evidence_paths: tuple[str | Path, ...] = (),
) -> dict[str, Any]:
    root = str(Path(project_root).resolve())
    runtime_evidence = _load_runtime_evidence(runtime_evidence_paths)
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case in cases:
        case_started = time.perf_counter()
        checks: list[dict[str, Any]] = []
        error = ""
        route = ""
        plan: dict[str, Any] = {}
        operations: list[str] = []
        generated_code_compiles = False
        result_text = ""
        result_type = ""
        result_elapsed_ms = 0.0
        try:
            decision = classify_prompt_route(case.prompt, project_roots=[root])
            route = str(decision.route or "")
            checks.append({
                "name": "route", "passed": route in case.expected_routes,
                "expected": list(case.expected_routes), "actual": route,
            })
            if case.pipeline:
                plan = plan_prompt_to_action_graph(case.prompt, [root])
                validation = validate_action_graph(plan)
                checks.append({
                    "name": "action_graph_valid", "passed": bool(validation.get("valid")),
                    "actual": list(validation.get("errors") or []),
                })
                operations = _operation_sequence(plan)
                checks.extend((
                    {
                        "name": "typed_pipeline_framework",
                        "passed": plan.get("framework") == "dynamic_typed_pipeline_v1",
                        "actual": plan.get("framework"),
                    },
                    {
                        "name": "hosts",
                        "passed": tuple(plan.get("hosts") or ()) == case.expected_hosts,
                        "expected": list(case.expected_hosts), "actual": list(plan.get("hosts") or []),
                    },
                    {
                        "name": "pipeline_success_contract",
                        "passed": bool(plan.get("success")) is case.expected_success,
                        "expected": case.expected_success, "actual": bool(plan.get("success")),
                    },
                ))
                if case.expected_operations:
                    checks.append({
                        "name": "operation_sequence",
                        "passed": _ordered_subsequence(case.expected_operations, operations),
                        "expected": list(case.expected_operations), "actual": operations,
                    })
                if case.expected_explicit_functions:
                    checks.append({
                        "name": "explicit_function_coverage",
                        "passed": len(plan.get("explicit_function_requests") or []) == case.expected_explicit_functions,
                        "expected": case.expected_explicit_functions,
                        "actual": len(plan.get("explicit_function_requests") or []),
                    })
                if case.expected_success:
                    preflight = preflight_pipeline_execution(plan, require_live_sessions=False)
                    checks.append({
                        "name": "structural_preflight", "passed": bool(preflight.get("ready")),
                        "actual": list(preflight.get("errors") or []),
                    })
                    workflow = workflow_plan_from_action_graph(plan)
                    checks.append({
                        "name": "workflow_materialization",
                        "passed": bool(workflow and workflow.get("success")),
                        "actual": list((workflow or {}).get("unresolved_inputs") or []),
                    })
                    if workflow and workflow.get("success"):
                        code = generate_pipeline_code_from_graph(
                            f"demo_{case.case_id}", case.prompt, workflow["steps"],
                        )
                        compile(code, f"<demo:{case.case_id}>", "exec")
                        generated_code_compiles = True
                    checks.append({
                        "name": "generated_python_compiles",
                        "passed": generated_code_compiles,
                    })
                else:
                    gap_kinds = [str(item.get("kind") or "") for item in plan.get("gaps") or []]
                    checks.append({
                        "name": "precise_safe_failure",
                        "passed": case.expected_gap_kind in gap_kinds and not operations,
                        "expected": case.expected_gap_kind, "actual": gap_kinds,
                    })
            else:
                checks.append({
                    "name": "official_route_selected",
                    "passed": bool(route and getattr(decision, "provider", "")),
                    "actual": {
                        "route": route,
                        "provider": str(getattr(decision, "provider", "") or ""),
                    },
                })
                if case.expected_result_terms or case.expected_result_type:
                    from tech_connector.engine.request_context import RequestContext
                    from tech_connector.engine.request_engine import RequestEngine

                    result_started = time.perf_counter()
                    result = RequestEngine(progress=lambda _event: None).process(
                        RequestContext(text=case.prompt, project_roots=[root])
                    )
                    result_elapsed_ms = round(
                        (time.perf_counter() - result_started) * 1000.0,
                        3,
                    )
                    result_text = str(result.text or "")
                    result_type = str((result.metadata or {}).get("result_type") or "")
                    checks.extend((
                        {
                            "name": "official_result_answered",
                            "passed": result.action == "answer" and bool(result_text),
                            "actual": result.action,
                        },
                        {
                            "name": "official_result_type",
                            "passed": not case.expected_result_type or result_type == case.expected_result_type,
                            "expected": case.expected_result_type,
                            "actual": result_type,
                        },
                        {
                            "name": "required_result_evidence",
                            "passed": all(term in result_text for term in case.expected_result_terms),
                            "expected": list(case.expected_result_terms),
                            "actual": [term for term in case.expected_result_terms if term in result_text],
                        },
                        {
                            "name": "forbidden_result_evidence",
                            "passed": not any(term in result_text for term in case.forbidden_result_terms),
                            "expected_absent": list(case.forbidden_result_terms),
                            "actual_present": [term for term in case.forbidden_result_terms if term in result_text],
                        },
                    ))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            checks.append({"name": "exception_free", "passed": False, "actual": error})

        qualified = bool(checks) and all(bool(item.get("passed")) for item in checks)
        if case.expected_result_terms or case.expected_result_type:
            evidence_level = "official_answer_content"
            end_to_end_qualified = qualified
        elif case.pipeline and not case.expected_success:
            evidence_level = "safe_failure_contract"
            end_to_end_qualified = qualified
        elif case.pipeline and qualified and case.case_id in runtime_evidence:
            evidence_level = "live_runtime_artifact_readback"
            end_to_end_qualified = True
        elif case.pipeline:
            evidence_level = "planning_materialization_codegen"
            end_to_end_qualified = False
        else:
            evidence_level = "route_only"
            end_to_end_qualified = False
        rows.append({
            **asdict(case),
            "route": route,
            "framework": plan.get("framework"),
            "hosts": list(plan.get("hosts") or []),
            "operations": operations,
            "qualified": qualified,
            "evidence_level": evidence_level,
            "end_to_end_qualified": end_to_end_qualified,
            "runtime_evidence": runtime_evidence.get(case.case_id, {}),
            "checks": checks,
            "error": error,
            "result_type": result_type,
            "result_text": result_text,
            "result_elapsed_ms": result_elapsed_ms,
            "elapsed_ms": round((time.perf_counter() - case_started) * 1000.0, 3),
        })

    failed = [row for row in rows if not row["qualified"]]
    end_to_end_unproven = [row for row in rows if not row["end_to_end_qualified"]]
    report = {
        "schema": DEVELOPER_PROMPT_DEMO_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": root,
        "ready_for_demo": not failed,
        "planning_ready": not failed,
        "ready_for_end_to_end_demo": not end_to_end_unproven,
        "summary": {
            "case_count": len(rows),
            "passed": len(rows) - len(failed),
            "failed": len(failed),
            "pipeline_cases": sum(bool(row["pipeline"]) for row in rows),
            "safe_failure_cases": sum(not bool(row["expected_success"]) for row in rows),
            "end_to_end_proven": len(rows) - len(end_to_end_unproven),
            "end_to_end_unproven": len(end_to_end_unproven),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        },
        "category_counts": {
            category: sum(row["category"] == category for row in rows)
            for category in sorted({row["category"] for row in rows})
        },
        "failed_case_ids": [row["case_id"] for row in failed],
        "end_to_end_unproven_case_ids": [row["case_id"] for row in end_to_end_unproven],
        "cases": rows,
        "scope": {
            "planning": "official prompt routing, deterministic action planning, and typed pipeline compilation",
            "execution": "generated Python is compiled; external DCC mutation is intentionally not performed",
            "live_host_validation": "covered separately by pipeline execution preflight when bridge sessions are connected",
        },
    }
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent),
        )
        try:
            with open(handle, "w", encoding="utf-8", closefd=True) as stream:
                json.dump(report, stream, indent=2, sort_keys=True)
                stream.write("\n")
            Path(temporary_name).replace(destination)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        report["report_path"] = str(destination)
    return report


__all__ = [
    "DEVELOPER_PROMPT_CASES", "DEVELOPER_PROMPT_DEMO_SCHEMA",
    "DeveloperPromptCase", "qualify_developer_demo_prompts",
]
