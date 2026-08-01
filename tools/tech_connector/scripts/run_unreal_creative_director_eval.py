"""Run non-mutating Unreal creative-director evaluation cases.

This script is intentionally read-only against Unreal. It measures whether the
assistant can combine live project evidence, capability-gap planning, approval
gates, and progress narration for creative Unreal requests.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.models.constants import TOOLS_ROOT, temp_output_path
from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan
from tech_connector.services.prompt.prompt_progress_service import build_prompt_progress_plan
from tech_connector.services.unreal.development_eval_service import record_unreal_development_eval


REPORT_DIR = temp_output_path("workspace", subdir="unreal_creative_director_eval")
RESULTS_JSON = REPORT_DIR / "results.json"
RESULTS_MD = REPORT_DIR / "results.md"


CASES = [
    {
        "name": "storm_shrine_niagara_interactable_missing_art",
        "prompt": (
            "In Unreal, make a procedural storm shrine with Niagara lightning, "
            "an interactable door, and missing rune assets if needed. Do not "
            "fake missing assets; plan reuse, placeholders, or source review."
        ),
        "expected_patterns": ["unreal.creative_environment_vfx"],
        "expected_nodes": [
            "existing_visual_assets",
            "missing_art_asset_plan",
            "niagara_effect_contract",
            "interaction_contract",
            "non_destructive_apply_plan",
        ],
        "expected_approval_strategy": "asset_source_search",
    },
    {
        "name": "motion_matching_climbing_no_fake_assets",
        "prompt": (
            "In Unreal, add motion matching climbing using whatever assets "
            "already exist; if pose search or animations are missing, plan the "
            "gap instead of creating fake assets."
        ),
        "expected_patterns": ["unreal.motion_matching"],
        "expected_nodes": [
            "pose_search_or_plugin",
            "animation_database",
            "animation_metadata",
            "runtime_integration",
        ],
    },
    {
        "name": "stamina_sprint_diagnose_only",
        "prompt": (
            "In Unreal, diagnose why the current third person character "
            "sprint/stamina feature would fail and only propose safe checks."
        ),
        "expected_patterns": ["unreal.character_stamina"],
        "expected_nodes": [
            "existing_movement_system",
            "stat_architecture",
            "stamina_contract",
            "sprint_integration",
        ],
    },
]


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def _json_loads(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _bridge_call(bridge: UnrealBridge, function: str, *, args=None, kwargs=None, timeout: float = 10.0) -> dict[str, Any]:
    started = time.perf_counter()
    result = bridge.safe_call(
        function,
        args=args or [],
        kwargs=kwargs or {},
        timeout=timeout,
        retries=0,
        retry_safe=True,
        label=function.rsplit(".", 1)[-1],
    )
    return {
        "ok": bool(result.get("ok")),
        "seconds": _elapsed(started),
        "error": result.get("error"),
        "data": _json_loads(result.get("data")),
    }


def _live_asset_inventory(bridge: UnrealBridge) -> dict[str, Any]:
    code = r"""
import json
import unreal

registry = unreal.AssetRegistryHelpers.get_asset_registry()
classes = [
    "Blueprint",
    "AnimBlueprint",
    "AnimSequence",
    "Skeleton",
    "SkeletalMesh",
    "InputAction",
    "InputMappingContext",
    "Material",
    "NiagaraSystem",
]
out = {}
for cls in classes:
    rows = []
    for data in registry.get_assets_by_path("/Game", recursive=True):
        try:
            class_name = str(data.asset_class_path.asset_name)
        except Exception:
            class_name = str(data.asset_class)
        if class_name == cls:
            rows.append({
                "name": str(data.asset_name),
                "path": str(data.package_name),
                "class": class_name,
            })
    out[cls] = {"count": len(rows), "sample": rows[:10]}
print(json.dumps(out))
"""
    started = time.perf_counter()
    result = bridge.execute_python(code, timeout=14, reset_globals=True)
    return {
        "ok": bool(result.get("ok")),
        "seconds": _elapsed(started),
        "error": result.get("error"),
        "data": _json_loads(result.get("data")),
    }


def _case_score(case: dict[str, Any], plan: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    expected_patterns = set(case.get("expected_patterns") or [])
    expected_nodes = set(case.get("expected_nodes") or [])
    actual_patterns = set(plan.get("matched_patterns") or [])
    actual_nodes = {str(node.get("key") or "") for node in plan.get("capability_nodes") or []}
    progress_states = [str(stage.get("state") or "") for stage in progress.get("stages") or []]
    approval_strategy = str(case.get("expected_approval_strategy") or "")
    approval_strategies = {str(gate.get("strategy") or "") for gate in plan.get("approval_gates") or []}
    checks = {
        "patterns": expected_patterns.issubset(actual_patterns),
        "nodes": expected_nodes.issubset(actual_nodes),
        "gap_progress": "GAP_DISCOVERY" in progress_states,
        "approval_gate": not approval_strategy or approval_strategy in approval_strategies,
        "no_generic_fallback": "generic.unreal" not in actual_patterns if expected_patterns else True,
    }
    passed = sum(1 for ok in checks.values() if ok)
    total = len(checks)
    return {
        "score": round((passed / total) * 100, 1),
        "checks": checks,
        "missing_patterns": sorted(expected_patterns - actual_patterns),
        "missing_nodes": sorted(expected_nodes - actual_nodes),
        "progress_states": progress_states,
        "approval_strategies": sorted(approval_strategies),
    }


def run_eval() -> dict[str, Any]:
    started = time.perf_counter()
    bridge = UnrealBridge()
    health_started = time.perf_counter()
    health = bridge.health_check(timeout=2.0)
    inventory = _live_asset_inventory(bridge) if health.get("connected") else {"ok": False, "data": {}}
    bp_context = _bridge_call(
        bridge,
        "tech_connector.bridges.unreal.unreal_blueprint_inspection.scan_blueprint",
        args=["/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter"],
        kwargs={"include_graphs": True, "include_defaults": True},
        timeout=20,
    ) if health.get("connected") else {"ok": False, "data": {}}
    live_evidence = {
        "health": {
            "connected": bool(health.get("connected")),
            "seconds": _elapsed(health_started),
            "engine_version": health.get("engine_version"),
            "project_name": health.get("project_name"),
            "loaded_level": health.get("loaded_level"),
            "warnings": list(health.get("warnings") or []),
        },
        "inventory": inventory,
        "blueprint_context": bp_context,
    }
    case_results: list[dict[str, Any]] = []
    for case in CASES:
        case_started = time.perf_counter()
        decision = {
            "host": "unreal",
            "route": "dcc_prototype",
            "allow_external_research": True,
            "allow_ingestion": False,
            "live_evidence": live_evidence,
        }
        plan = build_goal_gap_plan(case["prompt"], decision)
        progress = build_prompt_progress_plan(
            case["prompt"],
            {**decision, "capability_gap_plan": plan},
        )
        scoring = _case_score(case, plan, progress)
        status = "pass" if scoring["score"] >= 90 else "needs_attention"
        result = {
            "name": case["name"],
            "prompt": case["prompt"],
            "status": status,
            "seconds": _elapsed(case_started),
            "score": scoring,
            "matched_patterns": list(plan.get("matched_patterns") or []),
            "missing_links": list(plan.get("missing_links") or [])[:8],
            "approval_gates": list(plan.get("approval_gates") or [])[:5],
            "source_report_requirements": list(plan.get("source_report_requirements") or [])[:5],
            "progress_states": scoring["progress_states"],
            "top_resolution_options": list(plan.get("resolution_options") or [])[:3],
        }
        case_results.append(result)
        record_unreal_development_eval(
            case=case["name"],
            stage="creative_director_eval",
            status=status,
            issue="" if status == "pass" else "Creative Unreal planning missed expected pattern, gap, progress, or approval signal.",
            evidence={
                "score": scoring,
                "matched_patterns": result["matched_patterns"],
                "approval_gates": result["approval_gates"],
            },
            remediation="Update planner patterns, live context resolvers, or approval strategy routing.",
        )
    aggregate_score = round(
        sum(float(item["score"]["score"]) for item in case_results) / max(1, len(case_results)),
        1,
    )
    return {
        "framework": "unreal_creative_director_eval_v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "total_seconds": _elapsed(started),
        "aggregate_score": aggregate_score,
        "status": "pass" if aggregate_score >= 90 and all(item["status"] == "pass" for item in case_results) else "needs_attention",
        "live_evidence": live_evidence,
        "cases": case_results,
        "comparison_targets": [
            "Project-wide context before action",
            "Blueprint/asset/Niagara/material/animation gap awareness",
            "No fake assets or imaginary engine state",
            "Approval gate before external assets or mutation",
            "Validation and rollback plan as first-class output",
            "Reusable learning record after each evaluation",
        ],
    }


def _write_report(result: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Unreal Creative Director Eval",
        "",
        f"- status: {result.get('status')}",
        f"- aggregate score: {result.get('aggregate_score')}",
        f"- total seconds: {result.get('total_seconds')}",
        "",
        "## Live Evidence",
        "",
    ]
    health = dict((result.get("live_evidence") or {}).get("health") or {})
    lines.extend(
        [
            f"- connected: {health.get('connected')}",
            f"- engine: {health.get('engine_version')}",
            f"- project: {health.get('project_name')}",
            f"- level: {health.get('loaded_level')}",
            "",
            "## Cases",
            "",
        ]
    )
    for case in result.get("cases") or []:
        lines.extend(
            [
                f"### {case.get('name')}",
                "",
                f"- status: {case.get('status')}",
                f"- score: {(case.get('score') or {}).get('score')}",
                f"- matched patterns: {', '.join(case.get('matched_patterns') or [])}",
                f"- progress: {', '.join(case.get('progress_states') or [])}",
                f"- approval strategies: {', '.join((case.get('score') or {}).get('approval_strategies') or []) or 'none'}",
                "",
                "Top missing links:",
            ]
        )
        for link in list(case.get("missing_links") or [])[:5]:
            lines.append(f"- {link.get('label')} ({link.get('status')})")
        lines.append("")
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    result = run_eval()
    _write_report(result)
    print(json.dumps(result, indent=2, default=str)[:20000])
    print(f"Wrote {RESULTS_JSON}")
    print(f"Wrote {RESULTS_MD}")
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
