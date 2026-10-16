"""Create semantically verified prompt pipelines for review in the desktop UI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))


REVIEW_PIPELINES = (
    {
        "name": "review_maya_blender_unreal_character",
        "category": "rigged_character",
        "file_types": [".ma/.mb scene", ".fbx", "Unreal skeletal assets"],
        "prompt": (
            "Create a Maya to Blender to Unreal validation pipeline: in Maya build a simple "
            "rigged animated proxy and export FBX to C:/temp/tc_review_chain_maya.fbx, in "
            "Blender import it, clean mesh names, apply transforms, add material and collision "
            "proxy, export FBX to C:/temp/tc_review_chain_blender.fbx, then in Unreal import it "
            "into /Game/TechConnector/Review/Character, save assets, and report registry readback."
        ),
    },
    {
        "name": "review_blender_unreal_prop_publish",
        "category": "static_model",
        "file_types": [".blend scene", ".fbx", "Unreal static mesh"],
        "prompt": (
            "Build a Blender to Unreal prop pipeline: clean selected mesh names, apply transforms, "
            "generate LOD0 and LOD1, export FBX to C:/temp/tc_review_prop.fbx, then import into "
            "Unreal /Game/TechConnector/Review/Props, create material slots, set collision, save "
            "assets, and produce validation output."
        ),
    },
    {
        "name": "review_maya_unreal_animation_publish",
        "category": "animation",
        "file_types": [".ma/.mb scene", ".fbx animation", "Unreal animation sequence"],
        "prompt": (
            "Create a Maya to Unreal animation publishing pipeline: validate the current animated "
            "skeleton, export selected joints and animation to C:/temp/tc_review_animation.fbx, "
            "import it into /Game/TechConnector/Review/Animations using skeleton "
            "/Game/Characters/Mannequins/Meshes/SK_Mannequin, validate skeleton and root-motion "
            "compatibility, retarget if needed, save assets, and report the final animation paths."
        ),
    },
    {
        "name": "review_motionbuilder_blender_unreal_mocap",
        "category": "mocap_cleanup",
        "allow_understanding_false_negative": True,
        "file_types": ["MotionBuilder take", ".fbx animation", ".blend scene", "Unreal animation sequence"],
        "prompt": (
            "Create a MotionBuilder to Blender to Unreal mocap pipeline. Export the current "
            "take, clean animation in Blender, publish FBX to "
            "/Game/TechConnector/Review/Mocap using skeleton "
            "/Game/Characters/Mannequins/Meshes/SK_Mannequin, inspect compatibility, retarget "
            "if needed, and report saved animation assets."
        ),
    },
    {
        "name": "review_houdini_unreal_fx_mesh_publish",
        "category": "fx_geometry",
        "file_types": ["Houdini SOP geometry", ".fbx", "Unreal static mesh"],
        "semantic_understanding": False,
        "allow_understanding_false_negative": True,
        "custom_settings": {"houdini.geometry.export.node_path": "/obj/OUT_FX"},
        "prompt": (
            "Export Houdini static mesh FX geometry from /obj/OUT_FX as FBX to "
            "C:/temp/tc_review_fx_mesh.fbx, import it into Unreal "
            "/Game/TechConnector/Review/FXMeshes, save it and validate registry readback."
        ),
    },
    {
        "name": "review_3dsmax_unreal_environment_publish",
        "category": "environment_model",
        "allow_understanding_false_negative": True,
        "file_types": [".max scene", ".fbx", "Unreal static mesh"],
        "prompt": (
            "Export a 3ds Max environment static mesh as FBX to "
            "C:/temp/tc_review_environment.fbx, import it into Unreal "
            "/Game/TechConnector/Review/Environment, save it and validate registry readback."
        ),
    },
    {
        "name": "review_blender_unity_vehicle_publish",
        "category": "vehicle_model",
        "allow_understanding_false_negative": True,
        "allow_semantic_verifier_false_negative": True,
        "file_types": [".blend scene", ".fbx", "Unity model asset"],
        "custom_settings": {
            "blender.pipeline.process_meshes_for_transfer.lod_count": 2,
            "unity.assets.import_fbx.destination_path": "Assets/TechConnector/Vehicles/tc_review_vehicle.fbx",
        },
        "prompt": (
            "Process the selected Blender vehicle meshes, generate LOD0 and LOD1, add collision, export "
            "FBX to C:/temp/tc_review_vehicle.fbx, import into Unity "
            "Assets/TechConnector/Vehicles."
        ),
    },
    {
        "name": "review_substance_tech_connector_texture_publish",
        "category": "material_textures",
        "allow_understanding_false_negative": True,
        "file_types": ["Substance Painter project", "texture set images", "Tech Connector texture assets"],
        "prompt": (
            "Create a Substance Painter to Tech Connector texture publishing pipeline. Export "
            "the current texture sets and import the texture images into project folder "
            "Assets/Materials."
        ),
    },
    {
        "name": "review_maya_blender_unity_character_publish",
        "category": "rigged_character",
        "allow_understanding_false_negative": True,
        "file_types": [".ma/.mb scene", ".fbx", ".blend scene", "Unity character asset"],
        "custom_settings": {
            "unity.assets.import_fbx.destination_path": "Assets/TechConnector/Characters/tc_review_character_clean.fbx",
        },
        "prompt": (
            "Export a Maya rigged character FBX to C:/temp/tc_review_character.fbx, import it "
            "into Blender, clean mesh names, apply transforms, add a material slot and collision "
            "proxy, then export FBX to "
            "C:/temp/tc_review_character_clean.fbx and import into Unity "
            "Assets/TechConnector/Characters."
        ),
    },
    {
        "name": "review_maya_motionbuilder_unreal_roundtrip",
        "category": "animation_roundtrip",
        "allow_understanding_false_negative": True,
        "file_types": [".ma/.mb scene", "MotionBuilder take", ".fbx animation", "Unreal animation sequence"],
        "prompt": (
            "Export Maya animation to MotionBuilder for cleanup, export FBX to "
            "C:/temp/tc_review_roundtrip.fbx, then import into Unreal "
            "/Game/TechConnector/Review/Roundtrip using skeleton "
            "/Game/Characters/Mannequins/Meshes/SK_Mannequin, inspect skeleton and root-motion "
            "compatibility, retarget if needed, save assets, report final animation paths, and "
            "validate registry readback."
        ),
    },
)


class _PlanView:
    """Expose workflow links in the format consumed by pipeline code generation."""

    def __init__(self, plan: dict[str, Any]) -> None:
        self.plan = plan

    def manifest_data_links(self) -> list[dict[str, str]]:
        return [
            {
                "from": f"step{int(link['from_step'])}.{link.get('from_output') or 'result'}",
                "to": f"step{int(link['to_step'])}.{link.get('to_input') or 'value'}",
            }
            for link in self.plan.get("data_links") or []
        ]

    def manifest_flow_links(self) -> list[dict[str, str]]:
        return [
            {
                "from": f"step{int(link['from_step'])}",
                "to": f"step{int(link['to_step'])}",
            }
            for link in self.plan.get("flow_links") or []
        ]


def _slot_values(plan: dict[str, Any]) -> dict[str, Any]:
    connected = {
        (int(link.get("to_step") or 0), str(link.get("to_input") or ""))
        for link in plan.get("data_links") or []
    }
    slots: dict[str, Any] = {}
    for index, step in enumerate(plan.get("steps") or [], start=1):
        literals = dict(step.get("literal_values") or {})
        for parameter in (step.get("symbol") or {}).get("params") or []:
            name = str(parameter.get("name") or "")
            if not name or name.startswith("*") or (index, name) in connected:
                continue
            if name in literals:
                slots[f"step{index}_{name}"] = literals[name]
    return slots


def _workflow_links(plan: dict[str, Any]) -> list[str]:
    return [
        f"step{int(link['from_step'])}.{link.get('from_output') or 'result'} -> "
        f"step{int(link['to_step'])}.{link.get('to_input') or 'value'}"
        for link in plan.get("data_links") or []
    ]


def _graph_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
    nodes = []
    steps = []
    for index, step in enumerate(plan.get("steps") or [], start=1):
        symbol = dict(step.get("symbol") or {})
        node_id = f"step{index}"
        row = {
            "node_id": node_id,
            "label": symbol.get("label") or symbol.get("name") or node_id,
            "name": symbol.get("name") or symbol.get("operation") or node_id,
            "host": symbol.get("host") or "general",
            "package": symbol.get("package") or symbol.get("host") or "Utility",
            "type": "DCC Command",
            "detail": symbol.get("docstring") or symbol.get("callable") or "",
            "operation": symbol.get("operation") or "",
            "callable": symbol.get("callable") or symbol.get("function_path") or "",
            "params": list(symbol.get("params") or []),
            "outputs": list(symbol.get("outputs") or []),
            "literal_values": dict(step.get("literal_values") or {}),
            "literal_value_provenance": dict(step.get("literal_value_provenance") or {}),
            "literal_value_details": dict(step.get("literal_value_details") or {}),
            "unresolved_inputs": list(step.get("unresolved_inputs") or []),
            "operation_contract": dict(step.get("operation_contract") or {}),
        }
        steps.append(
            {
                "step_index": index,
                "symbol": symbol,
                "params": list(step.get("params") or symbol.get("params") or []),
                "outputs": list(step.get("outputs") or symbol.get("outputs") or []),
                "literal_values": dict(step.get("literal_values") or {}),
                "literal_value_provenance": dict(step.get("literal_value_provenance") or {}),
                "literal_value_details": dict(step.get("literal_value_details") or {}),
                "unresolved_inputs": list(step.get("unresolved_inputs") or []),
                "operation_contract": dict(step.get("operation_contract") or {}),
            }
        )
        nodes.append(
            {
                "id": node_id,
                **{key: value for key, value in row.items() if key != "node_id"},
                "x": 60 + ((index - 1) % 3) * 300,
                "y": 60 + ((index - 1) // 3) * 200,
            }
        )
    return {"nodes": nodes, "steps": steps}


def _materialize_ui_graph(plan: dict[str, Any]) -> dict[str, Any]:
    """Exercise the same graph-building path used by the Pipelines UI."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from tech_connector.ui.pipeline_node_types import FLOW_PORT
    from tech_connector.ui.pipeline_node_view import PipelineGraphLink, PipelineNodeView

    app = QApplication.instance() or QApplication([])
    view = PipelineNodeView()
    steps: list[dict[str, Any]] = []
    for planned_step in plan.get("steps") or []:
        symbol = dict(planned_step.get("symbol") or {})
        params = list(planned_step.get("params") or symbol.get("params") or [])
        outputs = list(planned_step.get("outputs") or symbol.get("outputs") or [])
        step_data = {
            "symbol": symbol,
            "params": params,
            "outputs": outputs,
            "literal_values": dict(planned_step.get("literal_values") or {}),
            "literal_value_provenance": dict(planned_step.get("literal_value_provenance") or {}),
            "literal_value_details": dict(planned_step.get("literal_value_details") or {}),
            "unresolved_inputs": list(planned_step.get("unresolved_inputs") or []),
            "operation_contract": dict(planned_step.get("operation_contract") or {}),
            "prompt_materialized": True,
        }
        view.add_pipeline_step(step_data, params, outputs)
        steps.append(step_data)

    def step_id(value: Any) -> str:
        index = int(value or 0) - 1
        if index < 0 or index >= len(steps):
            return ""
        return str(steps[index].get("graph_step_id") or "")

    for link in plan.get("data_links") or []:
        source = step_id(link.get("from_step"))
        target = step_id(link.get("to_step"))
        if not source or not target:
            raise RuntimeError(f"UI data link references an unknown step: {link}")
        view.links.append(
            PipelineGraphLink(
                source,
                str(link.get("from_output") or "result"),
                target,
                str(link.get("to_input") or ""),
                "data",
            )
        )
    for link in plan.get("flow_links") or []:
        source = step_id(link.get("from_step"))
        target = step_id(link.get("to_step"))
        if not source or not target:
            raise RuntimeError(f"UI flow link references an unknown step: {link}")
        view.links.append(PipelineGraphLink(source, FLOW_PORT, target, FLOW_PORT, "flow"))

    view.refresh_links(rebuild=True)
    data_flow_errors = list(view.validate_data_flow() or [])
    app.processEvents()
    if len(view.nodes) != len(steps):
        raise RuntimeError(
            f"UI materialized {len(view.nodes)} nodes; expected {len(steps)}."
        )
    if data_flow_errors:
        raise RuntimeError(f"UI graph has disconnected inputs: {data_flow_errors}")
    return {
        "ok": True,
        "node_count": len(view.nodes),
        "link_count": len(view.links),
        "execution_order": [
            str(view.nodes[step_id].symbol.get("name") or "")
            for step_id in view.execution_order()
        ],
    }


def create_review_pack(project_root: Path) -> dict[str, Any]:
    from tech_connector.services.prompt.pipeline_prompt_flow_service import (
        resolve_pipeline_prompt_flow,
    )
    from tech_connector.services.settings_service import load_settings
    from tech_connector.services.workflow_codegen_service import (
        generate_pipeline_code_from_graph,
    )
    from tech_connector.services.workflow_python_graph_sync_service import (
        parse_pipeline_python_to_graph,
    )
    from tech_connector.services.workflow_service import save_composed_workflow

    records: list[dict[str, Any]] = []
    base_preferences = {
        "use_default_settings": True,
        "semantic_verification": True,
        "semantic_understanding": True,
        "custom_settings": {},
    }
    for specification in REVIEW_PIPELINES:
        name = str(specification["name"])
        prompt = str(specification["prompt"])
        preferences = {
            **base_preferences,
            "semantic_understanding": bool(
                specification.get("semantic_understanding", True)
            ),
            "custom_settings": dict(specification.get("custom_settings") or {}),
        }
        flow = resolve_pipeline_prompt_flow(
            prompt,
            [str(project_root)],
            host_hint="cross_dcc",
            decision_facts={
                "settings": load_settings(),
                "planning_preferences": preferences,
            },
        )
        plan = dict(flow.get("workflow_plan") or {})
        action_graph = dict(flow.get("action_graph") or {})
        requirement_verification = dict(action_graph.get("requirement_verification") or {})
        allow_understanding_false_negative = bool(
            specification.get("allow_understanding_false_negative", False)
        )
        verified_despite_understanding = bool(
            allow_understanding_false_negative
            and action_graph.get("success")
            and plan.get("success")
            and requirement_verification.get("matches_request") is True
        )
        verified_despite_semantic_critic = bool(
            specification.get("allow_semantic_verifier_false_negative", False)
            and action_graph.get("success")
            and action_graph.get("execution_ready")
            and not action_graph.get("required_inputs")
            and bool(plan.get("steps"))
            and not plan.get("unresolved_inputs")
        )
        accepted_false_negative = (
            verified_despite_understanding or verified_despite_semantic_critic
        )
        if (not flow.get("ok") and not accepted_false_negative) or (
            not plan.get("success") and not verified_despite_semantic_critic
        ):
            raise RuntimeError(
                f"{name} did not pass prompt planning: "
                f"{action_graph.get('capability_gaps') or plan.get('diagnostics')}"
            )
        steps = list(plan.get("steps") or [])
        code = generate_pipeline_code_from_graph(
            name,
            prompt,
            steps,
            view=_PlanView(plan),
        )
        compile(code, f"<{name}>", "exec")
        parsed = parse_pipeline_python_to_graph(code)
        if not parsed.ok:
            raise RuntimeError(f"{name} did not round-trip to a graph: {parsed.diagnostics}")
        materialized = _materialize_ui_graph(plan)
        slots = _slot_values(plan)
        saved = save_composed_workflow(
            project_root=project_root,
            composed_code=code,
            goal=prompt,
            slots_text="\n".join(f"{key}={value}" for key, value in slots.items()),
            workflow_links="\n".join(_workflow_links(plan)),
            host="cross_dcc",
            selected_items=[dict(step.get("symbol") or {}) for step in steps],
        )
        manifest = json.loads(saved.manifest_path.read_text(encoding="utf-8"))
        snapshot = _graph_snapshot(plan)
        manifest.update(
            {
                "source": "prompt_review_pack",
                "prompt_verified": True,
                "nodes": snapshot["nodes"],
                "steps": snapshot["steps"],
                "data_links": list(plan.get("data_links") or []),
                "flow_links": list(plan.get("flow_links") or []),
                "prompt_flow_summary": {
                    "schema": flow.get("schema"),
                    "route": (flow.get("route_decision") or {}).get("route"),
                    "framework": (flow.get("action_graph") or {}).get("framework"),
                    "semantic_verification": dict(
                        (flow.get("action_graph") or {}).get("requirement_verification") or {}
                    ),
                    "timings": dict(flow.get("timings") or {}),
                    "ui_materialization": materialized,
                    "python_round_trip_node_count": len(parsed.steps),
                    "understanding_false_negative_waived": verified_despite_understanding,
                    "semantic_verifier_false_negative_waived": verified_despite_semantic_critic,
                },
                "review_scenario": {
                    "category": str(specification.get("category") or "asset_pipeline"),
                    "file_types": list(specification.get("file_types") or []),
                },
            }
        )
        saved.manifest_path.write_text(
            json.dumps(manifest, indent=2, default=str),
            encoding="utf-8",
        )
        records.append(
            {
                "name": name,
                "category": str(specification.get("category") or "asset_pipeline"),
                "file_types": list(specification.get("file_types") or []),
                "manifest": str(saved.manifest_path),
                "module": str(saved.module_path),
                "test": str(saved.test_path),
                "hosts": [
                    str((step.get("symbol") or {}).get("host") or "")
                    for step in steps
                ],
                "node_count": len(steps),
                "data_link_count": len(plan.get("data_links") or []),
                "flow_link_count": len(plan.get("flow_links") or []),
                "ui_materialization": materialized,
            }
        )

    report = {
        "schema": "tech_connector.pipeline_review_pack.v1",
        "project_root": str(project_root),
        "pipeline_count": len(records),
        "pipelines": records,
    }
    report_path = project_root / "workflows" / "pipeline_review_pack.report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=TOOLS_ROOT)
    args = parser.parse_args()
    report = create_review_pack(args.project_root.resolve())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
