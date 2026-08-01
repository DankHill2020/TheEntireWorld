from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from time import perf_counter
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tech_connector.models.constants import temp_output_path

from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.services.prompt.pipeline_prompt_flow_service import resolve_pipeline_prompt_flow
from tech_connector.services.workflow_codegen_service import (
    generate_pipeline_code_from_graph,
    workflow_function_name,
)


PROMPT = (
    "Create a Maya to Blender to Unreal validation pipeline: in Maya build a uniquely named simple rigged "
    "animated proxy without replacing the current scene and export FBX to C:/tmp/tc_chain_maya.fbx; in Blender "
    "import it, preserve the armature and animation, clean mesh names, apply transforms, add a validation material "
    "and LOD modifier, then export FBX to C:/tmp/tc_chain_blender.fbx; in Unreal import it as skeletal content into "
    "/Game/AIStudio/Validation/Chain, save every imported asset, then prove the handoff with asset-registry readback."
)


class _WorkflowPlanView:
    def __init__(self, plan: dict[str, Any]) -> None:
        self.plan = plan

    def ordered_step_data(self) -> list[dict[str, Any]]:
        return list(self.plan.get("steps") or [])

    def manifest_data_links(self) -> list[dict[str, str]]:
        return [
            {
                "from": f"step{link['from_step']}.{link['from_output']}",
                "to": f"step{link['to_step']}.{link['to_input']}",
            }
            for link in self.plan.get("data_links") or []
        ]

    def manifest_flow_links(self) -> list[dict[str, str]]:
        return [
            {
                "from": f"step{link['from_step']}.flow",
                "to": f"step{link['to_step']}.flow",
            }
            for link in self.plan.get("flow_links") or []
        ]


def _bridge_preflight() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for host, bridge in (
        ("maya", MayaBridge()),
        ("blender", BlenderBridge()),
        ("unreal", UnrealBridge()),
    ):
        started = perf_counter()
        row: dict[str, Any] = {"connected": False}
        try:
            if host == "unreal":
                health = bridge.health_check(timeout=1.5)
                row.update(health)
                row["connected"] = bool(health.get("connected"))
            else:
                port = bridge.find_port()
                row["port"] = port
                if port:
                    ok, output = bridge.execute("print('TC_CROSS_DCC_PREFLIGHT')", timeout=3.0)
                    row["connected"] = bool(ok)
                    row["output"] = output
        except Exception as exc:
            row["error"] = str(exc)
        row["elapsed_ms"] = round((perf_counter() - started) * 1000.0, 3)
        result[host] = row
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the canonical Pipeline View cross-DCC prompt flow.")
    parser.add_argument("--execute", action="store_true", help="Execute only when Maya, Blender, and Unreal preflight succeeds.")
    parser.add_argument(
        "--output",
        default=str(temp_output_path("official_cross_dcc_ui_flow.json", subdir="reports")),
    )
    args = parser.parse_args()

    report: dict[str, Any] = {"prompt": PROMPT}
    total_started = perf_counter()
    flow = resolve_pipeline_prompt_flow(PROMPT, [str(APP_ROOT)])
    report["flow"] = flow
    plan = dict(flow.get("workflow_plan") or {})

    code_started = perf_counter()
    code = generate_pipeline_code_from_graph(
        "official_cross_dcc_validation",
        PROMPT,
        plan.get("steps") or [],
        view=_WorkflowPlanView(plan),
    )
    compile(code, "<official-cross-dcc-ui-flow>", "exec")
    report["generated_code"] = code
    report["code_generation_ms"] = round((perf_counter() - code_started) * 1000.0, 3)

    preflight = _bridge_preflight()
    report["bridge_preflight"] = preflight
    report["execution_requested"] = bool(args.execute)
    report["execution"] = {"attempted": False, "ok": False}

    all_connected = all(bool(preflight.get(host, {}).get("connected")) for host in ("maya", "blender", "unreal"))
    if args.execute and flow.get("ok") and all_connected:
        execution_started = perf_counter()
        report["execution"]["attempted"] = True
        try:
            namespace: dict[str, Any] = {}
            exec(compile(code, "<official-cross-dcc-ui-flow>", "exec"), namespace, namespace)
            function_name = workflow_function_name("official_cross_dcc_validation")
            result = namespace[function_name]()
            report["execution"].update(
                {
                    "ok": True,
                    "function": function_name,
                    "result": result,
                    "stage_trace": list(namespace.get("_TC_PIPELINE_LAST_TRACE") or []),
                }
            )
        except Exception as exc:
            report["execution"].update(
                {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "stage_trace": list(namespace.get("_TC_PIPELINE_LAST_TRACE") or []),
                }
            )
        report["execution"]["elapsed_ms"] = round((perf_counter() - execution_started) * 1000.0, 3)
    elif args.execute:
        report["execution"]["blocked_reason"] = (
            "Prompt flow did not pass." if not flow.get("ok") else "One or more DCC bridges are disconnected."
        )

    report["total_ms"] = round((perf_counter() - total_started) * 1000.0, 3)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(
        {
            "report": str(output),
            "flow_ok": flow.get("ok"),
            "route": (flow.get("route_decision") or {}).get("route"),
            "nodes": len(plan.get("steps") or []),
            "data_links": len(plan.get("data_links") or []),
            "flow_links": len(plan.get("flow_links") or []),
            "preflight": {host: row.get("connected") for host, row in preflight.items()},
            "execution": report["execution"],
            "timings": flow.get("timings"),
            "code_generation_ms": report["code_generation_ms"],
            "total_ms": report["total_ms"],
        },
        indent=2,
        default=str,
    ))
    return 0 if flow.get("ok") and (not args.execute or report["execution"].get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
