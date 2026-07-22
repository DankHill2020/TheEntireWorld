"""Submit adversarial animation-system builds through the UI command flow."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.services.application_service import ApplicationService


CASES = [
    {
        "key": "ledge_corner_shimmy",
        "prompt": (
            "In the live Unreal project, build a playable ledge traversal animation system that enters a hang "
            "from a jump, shimmies left and right, turns around an outside corner, and jumps backward to another "
            "ledge. Intentionally do not substitute generic locomotion clips. Resolve the character mesh and "
            "Skeleton from live project evidence. Search existing project and ArtSource animation assets first; "
            "when the required contextual clips are absent, research and download commercially usable HTTPS "
            "animation sources, record license and provenance, retarget to the resolved target when compatibility "
            "is not measured, import under /Game/AIStudio/DownloadedAnimations, and integrate the animations. "
            "You are approved to perform those source, conversion, import, Blueprint, AnimBlueprint, compile, and "
            "PIE verification actions. Reject uncertain licenses and reject visually or contextually invalid motion. "
            "Do not report success unless the graph compiles and a matching runtime scenario observes the states "
            "and animation playback."
        ),
    },
    {
        "key": "prone_crawl_turn",
        "prompt": (
            "In the live Unreal project, build a playable prone traversal animation system for entering prone, "
            "crawling under a 70 cm obstacle, turning 180 degrees while prone, crawling backward, and returning to "
            "standing. Resolve the target character and Skeleton from live evidence. Audit project and ArtSource "
            "motions first, then deliberately acquire missing commercially usable animation over HTTPS, preserve "
            "license/provenance, retarget through a verified route when target proportions are not proven, import "
            "to a project asset folder, wire the runtime animation states, compile, and verify the actual sequence "
            "playback in PIE. This prompt approves the necessary download, conversion, import, graph edit, compile, "
            "and test actions. Never treat a successful import or metadata-only validation as runtime success."
        ),
    },
    {
        "key": "paired_disarm_takedown",
        "prompt": (
            "In the live Unreal project, build a playable synchronized combat disarm system with attacker and "
            "victim alignment, a failed-disarm branch, successful weapon removal, paired takedown animations, "
            "damage timing, cancellation, and recovery. Resolve each participating target Skeleton from live "
            "project evidence. Search project and ArtSource content, and intentionally acquire any missing paired "
            "motions from commercially usable HTTPS sources with provenance. Retarget every unproven source to "
            "the selected targets, import into the Unreal project, create the needed slots/montages and gameplay "
            "logic, compile all touched assets, and run a two-actor PIE scenario that proves alignment, montage "
            "playback, branch outcomes, and cleanup. The required download, conversion, import, graph mutation, "
            "compile, and test actions are approved. A plan, placeholder, or green asset reference check is not a "
            "successful result."
        ),
    },
]


def _asset_inventory() -> dict[str, Any]:
    code = r'''
import json
import unreal
registry = unreal.AssetRegistryHelpers.get_asset_registry()
rows = []
for data in registry.get_assets_by_path('/Game', recursive=True):
    try:
        class_name = str(data.asset_class_path.asset_name)
    except Exception:
        class_name = str(data.asset_class)
    if class_name in {'AnimSequence', 'AnimMontage', 'AnimBlueprint', 'IKRetargeter', 'IKRigDefinition'}:
        rows.append({'path': str(data.package_name), 'class': class_name})
print(json.dumps({'count': len(rows), 'ai_studio': [row for row in rows if row['path'].startswith('/Game/AIStudio')], 'classes': {name: sum(1 for row in rows if row['class'] == name) for name in sorted({row['class'] for row in rows})}}))
'''
    result = UnrealBridge().execute_python(code, timeout=30, reset_globals=True)
    return dict(result.get("data") or {}) if result.get("ok") else {"error": result.get("error")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=[row["key"] for row in CASES] + ["all"], default="all")
    parser.add_argument("--output", type=Path, default=Path(".ai_studio/intelligence/ui_animation_system_eval.json"))
    args = parser.parse_args()
    chosen = CASES if args.case == "all" else [row for row in CASES if row["key"] == args.case]
    settings = {
        "active_project": r"C:\depot\Time_Fighters 5.8",
        "extra_dirs": [r"C:\depot\tools", r"C:\depot\ArtSource"],
        "unreal_uproject_path": r"C:\depot\Time_Fighters 5.8\Time_Fighters.uproject",
        "model": "ollama:qwen3:14b",
        "model_source_mode": "local_only",
        "enable_live_sources": True,
        "research_project_snapshot": True,
        "research_unreal_capabilities": True,
        "research_official_docs": True,
        "research_best_practices": True,
        "research_web_techniques": True,
        "research_github_examples": True,
        "research_compare_architectures": True,
        "research_generate_plan": True,
        "research_auto_implement": True,
        "allow_unreal_cpp_bridge": True,
        "ai_work_memory_enabled": True,
        "expert_memory_packet_enabled": True,
        "multi_stage_reasoning_enabled": True,
        "multi_stage_reasoning_mode": "deterministic",
    }
    service = ApplicationService(settings=settings)
    report = {
        "schema": "ai_studio.ui_animation_system_eval.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "unreal_health": UnrealBridge().health_check(timeout=5),
        "before": _asset_inventory(),
        "cases": [],
    }
    for case in chosen:
        result = service.command_service.execute(
            "submit_prompt",
            {
                "prompt": case["prompt"],
                "active_tab": "Unreal",
                "project_roots": settings["extra_dirs"] + [settings["active_project"]],
                "extras": {
                    "host_hint": "unreal",
                    "settings": settings,
                    "approved_execution": True,
                    "allow_external_research": True,
                    "allow_ingestion": True,
                    "allow_mutation": True,
                    "require_runtime_verification": True,
                },
            },
        )
        report["cases"].append({"key": case["key"], "prompt": case["prompt"], "submission": result, "after": _asset_inventory()})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["after"] = _asset_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "cases": [{"key": row["key"], "ok": row["submission"].get("ok"), "status": (row["submission"].get("job") or {}).get("status"), "action": ((row["submission"].get("job") or {}).get("result") or {}).get("action")} for row in report["cases"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
