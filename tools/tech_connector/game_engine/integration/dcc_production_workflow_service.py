"""Role-specific, session-pinned production journeys for external DCC hosts."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tech_connector.bridges.session_preferences import preferred_session_port
from tech_connector.game_engine.integration.dcc_host_qualification_service import HOST_ROLE_PROFILES, bridge_for_host
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.dcc_receipt_integrity_service import (
    bridge_implementation_fingerprint,
    parse_receipt_datetime,
    receipt_environment_fingerprint,
    stable_receipt_digest,
)
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    source_file_fingerprint,
    stable_scene_source_id,
)
from tech_connector.models.constants import APP_DIR


WORKFLOW_SCHEMA = "tech_connector.dcc_production_workflows.v1"
WORKFLOW_RECEIPT_SCHEMA = "tech_connector.dcc_workflow_receipt.v2"
WORKFLOW_LEDGER_SCHEMA = "tech_connector.dcc_workflow_receipt_ledger.v1"
DEFAULT_WORKFLOW_RECEIPT_MAX_AGE_SECONDS = 24.0 * 60.0 * 60.0
DEFAULT_WORKFLOW_LEDGER_PATH = Path(APP_DIR) / "dcc_workflow_receipts.json"


@dataclass(frozen=True)
class DccWorkflowStep:
    operation: str
    label: str
    params: dict[str, Any] = field(default_factory=dict)
    readback: bool = False
    artifact_parameters: tuple[str, ...] = ()
    output_artifact_keys: tuple[str, ...] = ()
    artifact_parity_checks: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DccProductionWorkflow:
    key: str
    host: str
    label: str
    role: str
    steps: tuple[DccWorkflowStep, ...]
    portable_outputs: tuple[str, ...]
    restoration_requirements: tuple[str, ...]
    parity_checks: tuple[str, ...]


@dataclass(frozen=True)
class DccWorkflowReceipt:
    workflow: str
    host: str
    session_port: int | None
    status: str
    steps: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]
    readback_complete: bool
    duration_ms: float
    artifact_readback_complete: bool = True
    parity_results: dict[str, bool] = field(default_factory=dict)
    parity_readback_complete: bool = False
    missing_gates: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    checked_at: str = ""
    receipt_id: str = ""
    environment_fingerprint: str = ""
    bridge_implementation: dict[str, Any] = field(default_factory=dict)
    workflow_contract_digest: str = ""
    integrity: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _step(operation: str, label: str, params: dict[str, Any] | None = None, **kwargs: Any) -> DccWorkflowStep:
    return DccWorkflowStep(operation, label, dict(params or {}), **kwargs)


PRODUCTION_WORKFLOWS: dict[str, DccProductionWorkflow] = {
    "maya.character_asset": DccProductionWorkflow(
        "maya.character_asset", "maya", "Build And Export Character Asset", HOST_ROLE_PROFILES["maya"].role,
        (
            _step(
                "pipeline.create_rigged_proxy", "Create skinned animated character proxy",
                {"name_prefix": "TC_WorkflowCharacter", "start_frame": 1, "end_frame": 24},
            ),
            _step(
                "animation.export", "Export animated FBX",
                {
                    "export_path": "{workspace}/maya_character.fbx",
                    "start_frame": 1,
                    "end_frame": 24,
                    "selected_only": True,
                    "nodes": ["TC_WorkflowCharacter_Mesh", "TC_WorkflowCharacter_Root"],
                },
                artifact_parameters=("export_path",),
            ),
            _step(
                "pipeline.inspect_rigged_proxy", "Verify rig, skin, animation, and material",
                {"name_prefix": "TC_WorkflowCharacter", "start_frame": 1, "end_frame": 24},
                readback=True,
            ),
        ),
        ("fbx", "tcskin", "tcscene", "source_link_manifest"),
        ("source path and fingerprint", "selected Maya session", "stable node IDs", "cached scene snapshot"),
        ("joint hierarchy", "skin influence count and normalization", "animation frame range", "material assignments"),
    ),
    "blender.generalist_asset": DccProductionWorkflow(
        "blender.generalist_asset", "blender", "Model, Shade, Animate, And Export", HOST_ROLE_PROFILES["blender"].role,
        (
            _step("modeling.create_primitive", "Create mesh", {"primitive_type": "cube", "name": "TC_WorkflowMesh"}),
            _step("material.create", "Create material", {"material_name": "TC_WorkflowMaterial", "color": [0.35, 0.55, 0.8, 1.0]}),
            _step("material.assign", "Assign material", {"material_name": "TC_WorkflowMaterial", "objects": ["TC_WorkflowMesh"]}),
            _step("animation.set_key", "Set first animation key", {"object_name": "TC_WorkflowMesh", "data_path": "location", "index": 0, "frame": 1, "value": 0.0}),
            _step("animation.set_key", "Set last animation key", {"object_name": "TC_WorkflowMesh", "data_path": "location", "index": 0, "frame": 24, "value": 2.0}),
            _step("animation.bake", "Bake animation", {"start_frame": 1, "end_frame": 24}),
            _step(
                "io.export_fbx", "Export FBX",
                {
                    "filepath": "{workspace}/blender_asset.fbx",
                    "selected_only": False,
                    "apply_unit_scale": True,
                    "axis_forward": "-Z",
                    "axis_up": "Y",
                },
                readback=True,
                artifact_parameters=("filepath",),
            ),
            _step(
                "workflow.inspect_generalist_asset", "Verify mesh, lookdev, and animation",
                {
                    "object_name": "TC_WorkflowMesh",
                    "material_name": "TC_WorkflowMaterial",
                    "start_frame": 1,
                    "end_frame": 24,
                },
                readback=True,
            ),
        ),
        ("fbx", "gltf", "usd", "textures", "source_link_manifest"),
        ("blend path and fingerprint", "selected Blender session", "object and material IDs", "cached scene snapshot"),
        ("topology", "UV and materials", "animation range", "coordinate conversion"),
    ),
    "3dsmax.modifier_asset": DccProductionWorkflow(
        "3dsmax.modifier_asset", "3dsmax", "Build Modifier Asset And Export", HOST_ROLE_PROFILES["3dsmax"].role,
        (
            _step("mesh.create_box", "Create box", {"name": "TC_WorkflowBox", "size": [10.0, 10.0, 10.0]}),
            _step("mesh.apply_modifier", "Apply modifier", {"node": "TC_WorkflowBox", "modifier": "Bend", "parameters": {"angle": 20.0}}),
            _step("material.create", "Create material", {"material_name": "TC_WorkflowMaterial"}),
            _step("material.assign", "Assign material", {"material_name": "TC_WorkflowMaterial", "nodes": ["TC_WorkflowBox"]}),
            _step("animation.set_key", "Set animation key", {"node": "TC_WorkflowBox", "attribute": "position.x", "frame": 24, "value": 25.0}),
            _step("io.export", "Export asset", {"filepath": "{workspace}/max_asset.fbx"}, artifact_parameters=("filepath",)),
            _step(
                "workflow.inspect_modifier_asset", "Verify modifier asset",
                {
                    "node": "TC_WorkflowBox",
                    "modifier": "Bend",
                    "modifier_parameters": {"angle": 20.0},
                    "material_name": "TC_WorkflowMaterial",
                    "animation_attribute": "position.x",
                    "animation_frame": 24,
                    "animation_value": 25.0,
                    "export_path": "{workspace}/max_asset.fbx",
                },
                readback=True,
            ),
        ),
        ("fbx", "usd", "materials", "source_link_manifest"),
        ("max path and fingerprint", "selected Max session", "modifier stack summary", "cached scene snapshot"),
        ("editable topology and modifier stack", "modifier parameters", "material assignment", "animation keys"),
    ),
    "motionbuilder.retarget_plot": DccProductionWorkflow(
        "motionbuilder.retarget_plot", "motionbuilder", "Characterize, Retarget, Plot, And Export", HOST_ROLE_PROFILES["motionbuilder"].role,
        (
            _step("io.import_fbx", "Import character FBX", {"filepath": "{workspace}/source_character.fbx"}),
            _step("character.create_character", "Create characterization", {"character_name": "TC_WorkflowCharacter"}),
            _step("character.plot_animation", "Plot retargeted animation", {"character_name": "TC_WorkflowCharacter", "plot_to_rig": True, "fps": 24}),
            _step("io.export_fbx", "Export plotted FBX", {"filepath": "{workspace}/motionbuilder_plotted.fbx"}, artifact_parameters=("filepath",)),
            _step("character.inspect", "Read back characterization and plotted curves", {"character_name": "TC_WorkflowCharacter"}, readback=True),
        ),
        ("fbx", "animation_take", "character_definition", "source_link_manifest"),
        ("fbx path and fingerprint", "selected MotionBuilder session", "take and character identity", "cached scene snapshot"),
        ("character mapping", "root motion", "take range and frame rate", "plotted transform curves"),
    ),
    "houdini.procedural_fx": DccProductionWorkflow(
        "houdini.procedural_fx", "houdini", "Build Procedural FX And Export USD", HOST_ROLE_PROFILES["houdini"].role,
        (
            _step("node.create", "Create geometry network", {"node_type": "geo", "parent": "/obj", "name": "tc_workflow_geo"}),
            _step("node.create", "Create source geometry", {"node_type": "sphere", "parent": "/obj/tc_workflow_geo", "name": "tc_workflow_sphere"}),
            _step("node.create", "Create geometry transform", {"node_type": "xform", "parent": "/obj/tc_workflow_geo", "name": "tc_workflow_xform"}),
            _step("node.connect", "Connect geometry network", {"source_path": "/obj/tc_workflow_geo/tc_workflow_sphere", "destination_path": "/obj/tc_workflow_geo/tc_workflow_xform"}),
            _step("node.create", "Create simulation network", {"node_type": "dopnet", "parent": "/obj", "name": "tc_workflow_dop"}),
            _step("simulation.run", "Cook simulation", {"dop_network_path": "/obj/tc_workflow_dop", "start_frame": 1, "end_frame": 24}),
            _step("usd.export", "Export USD", {"filepath": "{workspace}/houdini_fx.usd", "node_path": "/obj/tc_workflow_geo/tc_workflow_xform", "frame_range": [1, 24]}),
            _step(
                "workflow.inspect_procedural_fx", "Verify procedural network and USD",
                {
                    "source_node": "/obj/tc_workflow_geo/tc_workflow_sphere",
                    "transform_node": "/obj/tc_workflow_geo/tc_workflow_xform",
                    "dop_network_path": "/obj/tc_workflow_dop",
                    "usd_path": "{workspace}/houdini_fx.usd",
                    "start_frame": 1,
                    "end_frame": 24,
                },
                readback=True,
                output_artifact_keys=("absolute_path",),
            ),
        ),
        ("usd", "bgeo_cache", "vdb", "source_link_manifest"),
        ("hip path and fingerprint", "selected Houdini session", "node paths and parameter values", "cached scene snapshot"),
        ("node topology", "simulation frame range", "geometry bounds", "USD composition"),
    ),
    "substance_painter.texture_set": DccProductionWorkflow(
        "substance_painter.texture_set", "substance_painter", "Author And Export PBR Texture Set", HOST_ROLE_PROFILES["substance_painter"].role,
        (
            _step("project.create", "Create project", {"mesh_path": "{workspace}/source_mesh.fbx"}),
            _step("material.apply", "Apply material", {"material_name": "TC_WorkflowMaterial"}),
            _step("textures.export", "Export PBR textures", {"output_path": "{workspace}/textures", "resolution": 2048}, readback=True, artifact_parameters=("output_path",)),
        ),
        ("spp", "base_color", "normal", "roughness", "metallic", "ao", "source_link_manifest"),
        ("spp path and fingerprint", "selected Painter session", "texture-set identity", "export preset"),
        (
            "texture-set names", "stack and UV-tile coverage",
            "requested channel resolution", "exported map inventory",
        ),
    ),
    "unreal.gameplay_vertical_slice": DccProductionWorkflow(
        "unreal.gameplay_vertical_slice", "unreal", "Build And Validate Gameplay Vertical Slice", HOST_ROLE_PROFILES["unreal"].role,
        (
            _step("blueprint.create_from_template", "Create Blueprint", {"template": "Actor", "asset_path": "/Game/TC/BP_Workflow"}),
            _step("blueprint.compile_and_save", "Compile and save Blueprint", {"asset_path": "/Game/TC/BP_Workflow"}, readback=True),
            _step("runtime.pie_begin", "Start play validation"),
            _step("runtime.pie_validate", "Validate runtime", {"target_assets": ["/Game/TC/BP_Workflow"]}, readback=True),
            _step("runtime.pie_end", "End play validation"),
            _step(
                "assets.inspect", "Read back saved Blueprint artifact",
                {"asset_path": "/Game/TC/BP_Workflow"},
                readback=True,
                output_artifact_keys=("absolute_path",),
            ),
        ),
        ("uasset", "tcpackage", "runtime_observation", "source_link_manifest"),
        ("uproject path and fingerprint", "selected Unreal session", "asset paths and package hashes", "loaded level"),
        ("Blueprint compile", "asset registry readback", "PIE behavior", "references and save state"),
    ),
    "unity.prefab_asset": DccProductionWorkflow(
        "unity.prefab_asset", "unity", "Import Asset And Assemble Prefab", HOST_ROLE_PROFILES["unity"].role,
        (
            _step(
                "assets.import_fbx", "Import and instantiate FBX",
                {
                    "filepath": "{workspace}/source_mesh.fbx",
                    "destination_path": "Assets/Models/TC_WorkflowAsset.fbx",
                    "instantiate": True,
                    "gameobject_name": "TC_WorkflowAsset",
                },
                output_artifact_keys=("absolute_path",),
            ),
            _step(
                "material.create", "Create material",
                {
                    "material_name": "TC_WorkflowMaterial",
                    "destination_path": "Assets/Materials/TC_WorkflowMaterial.mat",
                },
                output_artifact_keys=("absolute_path",),
            ),
            _step(
                "material.assign", "Assign material",
                {"gameobject_name": "TC_WorkflowAsset", "material_path": "Assets/Materials/TC_WorkflowMaterial.mat"},
            ),
            _step(
                "prefab.create", "Create prefab",
                {"gameobject_name": "TC_WorkflowAsset", "destination_path": "Assets/Prefabs/TC_WorkflowAsset.prefab"},
                output_artifact_keys=("absolute_path",),
            ),
            _step(
                "scene.add_prefab", "Add prefab to scene",
                {"prefab_path": "Assets/Prefabs/TC_WorkflowAsset.prefab", "instance_name": "TC_WorkflowInstance"},
            ),
            _step(
                "workflow.inspect_prefab_asset", "Verify imported asset and scene instance",
                {
                    "model_path": "Assets/Models/TC_WorkflowAsset.fbx",
                    "material_path": "Assets/Materials/TC_WorkflowMaterial.mat",
                    "prefab_path": "Assets/Prefabs/TC_WorkflowAsset.prefab",
                    "instance_name": "TC_WorkflowInstance",
                    "position": [0.0, 0.0, 0.0],
                },
                readback=True,
            ),
        ),
        ("prefab", "material", "mesh", "tcpackage", "source_link_manifest"),
        ("Unity project path and fingerprint", "selected Unity session", "asset GUIDs", "scene path"),
        ("mesh import settings", "material bindings", "prefab hierarchy", "scene instance transform"),
    ),
    "photoshop.layered_texture": DccProductionWorkflow(
        "photoshop.layered_texture", "photoshop", "Edit And Validate Layered Texture", HOST_ROLE_PROFILES["photoshop"].role,
        (
            _step("document.info", "Inspect document"),
            _step("layer.list", "Read layer stack"),
            _step("document.batch_play", "Apply explicit image edit", {"descriptor": {"_obj": "select", "_target": [{"_ref": "layer", "_enum": "ordinal", "_value": "targetEnum"}]}}),
            _step(
                "document.info", "Read back edited document", readback=True,
                output_artifact_keys=("file_path",),
                artifact_parity_checks={"document file checksum": "file_path"},
            ),
        ),
        ("psd", "png", "tiff", "layer_manifest", "source_link_manifest"),
        ("document path and fingerprint", "selected Photoshop session", "document and layer IDs", "color profile"),
        ("dimensions and bit depth", "layer order", "color profile", "document file checksum"),
    ),
    "gimp.pbr_texture_pack": DccProductionWorkflow(
        "gimp.pbr_texture_pack", "gimp", "Convert And Pack PBR Textures", HOST_ROLE_PROFILES["gimp"].role,
        (
            _step("image.convert_batch", "Convert source images", {"files": ["{workspace}/roughness.png", "{workspace}/metallic.png", "{workspace}/ao.png"], "target_format": "png"}),
            _step(
                "texture.pack_pbr", "Pack ORM texture",
                {
                    "roughness_path": "{workspace}/roughness.png",
                    "metallic_path": "{workspace}/metallic.png",
                    "ao_path": "{workspace}/ao.png",
                    "output_path": "{workspace}/orm.png",
                },
                readback=True,
                artifact_parameters=("output_path",),
                artifact_parity_checks={"output pixel checksum": "output_path"},
            ),
            _step("script.run", "Read back GIMP identity", {"code": "result = 'tc_workflow_readback'"}, readback=True),
        ),
        ("png", "tiff", "orm_texture", "source_link_manifest"),
        ("image paths and fingerprints", "selected GIMP session", "layer and image IDs", "color profile"),
        ("dimensions", "channel packing", "color space", "output pixel checksum"),
    ),
}


def validate_workflow_catalog() -> dict[str, Any]:
    errors: list[str] = []
    delegated_steps: dict[str, list[str]] = {}
    by_host: dict[str, int] = {host: 0 for host in HOST_ROLE_PROFILES}
    for key, workflow in PRODUCTION_WORKFLOWS.items():
        if key != workflow.key:
            errors.append(f"{key}: mapping key does not match workflow key")
        if workflow.host not in HOST_ROLE_PROFILES:
            errors.append(f"{key}: unsupported host {workflow.host}")
            continue
        by_host[workflow.host] += 1
        registry = dcc_operation_registry(workflow.host)
        for step in workflow.steps:
            if step.operation not in registry:
                errors.append(f"{key}: unregistered operation {step.operation}")
                continue
            operation = registry[step.operation]
            if str(getattr(operation, "execution_mode", "host_native")) == "user_delegated":
                delegated_steps.setdefault(key, []).append(step.operation)
        if not any(step.readback for step in workflow.steps):
            errors.append(f"{key}: no readback step")
        if not workflow.portable_outputs or "source_link_manifest" not in workflow.portable_outputs:
            errors.append(f"{key}: portable source-link output is missing")
        if not workflow.restoration_requirements:
            errors.append(f"{key}: restoration contract is missing")
        if not workflow.parity_checks:
            errors.append(f"{key}: parity contract is missing")
    for host, count in by_host.items():
        if count == 0:
            errors.append(f"{host}: no production workflow")
    return {
        "schema": WORKFLOW_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "workflow_count": len(PRODUCTION_WORKFLOWS),
        "host_count": sum(count > 0 for count in by_host.values()),
        "workflows_by_host": by_host,
        "delegated_steps": delegated_steps,
    }


def plan_dcc_workflow(
    workflow_key: str,
    *,
    workspace: str | Path,
    step_inputs: dict[str, dict[str, Any]] | None = None,
    session_port: int | None = None,
) -> dict[str, Any]:
    workflow = PRODUCTION_WORKFLOWS.get(str(workflow_key or ""))
    if workflow is None:
        raise KeyError(f"Unknown DCC production workflow: {workflow_key}")
    workspace_path = str(Path(workspace).expanduser().resolve())
    overrides = dict(step_inputs or {})
    registry = dcc_operation_registry(workflow.host)
    steps = []
    for index, step in enumerate(workflow.steps):
        operation = registry[step.operation]
        params = dict(operation.optional)
        params.update(_resolve_workspace_tokens(step.params, workspace_path))
        params.update(dict(overrides.get(step.operation) or overrides.get(str(index)) or {}))
        missing = [name for name in operation.required if name not in params or params[name] in (None, "")]
        steps.append({
            "index": index,
            "operation": step.operation,
            "label": step.label,
            "callable": operation.function,
            "params": params,
            "mutates_project": bool(operation.mutates_project),
            "execution_mode": str(getattr(operation, "execution_mode", "host_native")),
            "readback": bool(step.readback),
            "artifact_parameters": list(step.artifact_parameters),
            "output_artifact_keys": list(step.output_artifact_keys),
            "artifact_parity_checks": dict(step.artifact_parity_checks),
            "missing_inputs": missing,
        })
    return {
        "schema": WORKFLOW_SCHEMA,
        "workflow": workflow.key,
        "host": workflow.host,
        "role": workflow.role,
        "session_port": int(session_port) if session_port is not None else None,
        "workspace": workspace_path,
        "steps": steps,
        "portable_outputs": list(workflow.portable_outputs),
        "restoration_requirements": list(workflow.restoration_requirements),
        "parity_checks": list(workflow.parity_checks),
        "valid": not any(step["missing_inputs"] for step in steps),
    }


def execute_dcc_workflow(
    workflow_key: str,
    *,
    workspace: str | Path,
    step_inputs: dict[str, dict[str, Any]] | None = None,
    session_port: int | None = None,
    confirm_mutating: bool = False,
    delegated_step_receipts: dict[str, dict[str, Any]] | None = None,
    executor: Callable[[str, str, str, dict[str, Any], int | None], Any] | None = None,
) -> DccWorkflowReceipt:
    plan = plan_dcc_workflow(
        workflow_key, workspace=workspace, step_inputs=step_inputs, session_port=session_port,
    )
    if not plan["valid"]:
        missing = [f"{row['operation']}: {', '.join(row['missing_inputs'])}" for row in plan["steps"] if row["missing_inputs"]]
        raise ValueError("Missing workflow inputs: " + "; ".join(missing))
    if any(row["mutates_project"] for row in plan["steps"]) and not confirm_mutating:
        raise PermissionError("This workflow changes the target DCC project; explicit confirmation is required.")
    run = executor or _execute_step
    started = time.perf_counter()
    receipts: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    readback_complete = True
    artifact_readback_complete = True
    parity_results: dict[str, bool] = {}
    delegation_receipts = dict(delegated_step_receipts or {})
    for row in plan["steps"]:
        step_started = time.perf_counter()
        if row["execution_mode"] == "user_delegated":
            delegated = dict(
                delegation_receipts.get(row["operation"])
                or delegation_receipts.get(str(row["index"]))
                or {}
            )
            ok = delegated.get("confirmed") is True
            output = {
                "delegated": True,
                "confirmed": ok,
                "confirmed_by": str(delegated.get("confirmed_by") or ""),
                "evidence": dict(delegated.get("evidence") or {}),
            }
            if not ok:
                output["error"] = (
                    f"{row['operation']} requires an explicit host-UI delegation receipt before the workflow can continue."
                )
        else:
            try:
                raw = run(plan["host"], row["operation"], row["callable"], dict(row["params"]), plan["session_port"])
                ok, output = _normalize_execution_result(raw)
            except Exception as exc:
                ok, output = False, {"error": str(exc)}
        receipt = {
            "index": row["index"],
            "operation": row["operation"],
            "label": row["label"],
            "ok": ok,
            "readback": row["readback"],
            "execution_mode": row["execution_mode"],
            "output": output,
            "duration_ms": (time.perf_counter() - step_started) * 1000.0,
        }
        receipts.append(receipt)
        if row["readback"] and ok:
            raw_parity = output.get("parity_checks")
            if isinstance(raw_parity, dict):
                parity_results.update({str(key): bool(value) for key, value in raw_parity.items()})
        for parameter in row["artifact_parameters"]:
            value = row["params"].get(parameter)
            if value:
                path = Path(str(value)).expanduser()
                fingerprint = source_file_fingerprint(path)
                artifact = {
                    "operation": row["operation"],
                    "parameter": parameter,
                    "path": str(path),
                    "exists": bool(fingerprint.get("exists")),
                    "fingerprint": fingerprint,
                }
                artifacts.append(artifact)
                if ok and not artifact["exists"]:
                    artifact_readback_complete = False
                    errors.append(f"{row['operation']}: expected artifact was not created: {path}")
                for check, artifact_key in row["artifact_parity_checks"].items():
                    if artifact_key == parameter:
                        parity_results[str(check)] = bool(
                            artifact["exists"] and fingerprint.get("head_sha256")
                        )
        for key in row["output_artifact_keys"]:
            value = output.get(key)
            if not value:
                if ok:
                    artifact_readback_complete = False
                    errors.append(f"{row['operation']}: output artifact path was not returned: {key}")
                continue
            path = Path(str(value)).expanduser()
            fingerprint = source_file_fingerprint(path)
            artifact = {
                "operation": row["operation"],
                "output_key": key,
                "path": str(path),
                "exists": bool(fingerprint.get("exists")),
                "fingerprint": fingerprint,
            }
            artifacts.append(artifact)
            if ok and not artifact["exists"]:
                artifact_readback_complete = False
                errors.append(f"{row['operation']}: returned artifact does not exist: {path}")
            for check, artifact_key in row["artifact_parity_checks"].items():
                if artifact_key == key:
                    parity_results[str(check)] = bool(
                        artifact["exists"] and fingerprint.get("head_sha256")
                    )
        if row["readback"] and not ok:
            readback_complete = False
        if not ok:
            errors.append(f"{row['operation']}: {output.get('error') or output}")
            break
    workflow = PRODUCTION_WORKFLOWS[plan["workflow"]]
    parity_readback_complete = bool(workflow.parity_checks) and all(
        parity_results.get(check) is True for check in workflow.parity_checks
    )
    missing_gates: list[str] = []
    if not readback_complete:
        missing_gates.append("workflow_readback")
    if not artifact_readback_complete:
        missing_gates.append("artifact_readback")
    if not parity_readback_complete:
        missing_gates.append("parity_readback")
    if errors:
        status = "failed"
    elif readback_complete and artifact_readback_complete and parity_readback_complete:
        status = "verified"
    else:
        status = "completed_unverified"
    checked_at = datetime.now(timezone.utc).isoformat()
    environment = receipt_environment_fingerprint()
    try:
        bridge_implementation = bridge_implementation_fingerprint(bridge_for_host(plan["host"]))
    except Exception:
        bridge_implementation = {}
    workflow_contract_digest = stable_receipt_digest(asdict(workflow))
    integrity = {
        "schema": WORKFLOW_RECEIPT_SCHEMA,
        "checked_at": checked_at,
        "workflow": plan["workflow"],
        "host": plan["host"],
        "session_port": plan["session_port"],
        "status": status,
        "steps": receipts,
        "artifacts": artifacts,
        "readback_complete": readback_complete,
        "artifact_readback_complete": artifact_readback_complete,
        "parity_results": parity_results,
        "parity_readback_complete": parity_readback_complete,
        "missing_gates": missing_gates,
        "errors": errors,
        "environment_fingerprint": environment,
        "bridge_implementation": bridge_implementation,
        "workflow_contract_digest": workflow_contract_digest,
    }
    return DccWorkflowReceipt(
        workflow=plan["workflow"],
        host=plan["host"],
        session_port=plan["session_port"],
        status=status,
        steps=tuple(receipts),
        artifacts=tuple(artifacts),
        readback_complete=readback_complete,
        duration_ms=(time.perf_counter() - started) * 1000.0,
        artifact_readback_complete=artifact_readback_complete,
        parity_results=parity_results,
        parity_readback_complete=parity_readback_complete,
        missing_gates=tuple(missing_gates),
        errors=tuple(errors),
        checked_at=checked_at,
        receipt_id=stable_receipt_digest(integrity),
        environment_fingerprint=environment,
        bridge_implementation=bridge_implementation,
        workflow_contract_digest=workflow_contract_digest,
        integrity=integrity,
    )


def validate_workflow_receipt(
    workflow_key: str,
    receipt: DccWorkflowReceipt | dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_WORKFLOW_RECEIPT_MAX_AGE_SECONDS,
    bridge: Any | None = None,
    check_artifacts: bool = True,
) -> dict[str, Any]:
    workflow = PRODUCTION_WORKFLOWS.get(str(workflow_key or ""))
    row = receipt.to_dict() if isinstance(receipt, DccWorkflowReceipt) else (
        dict(receipt or {}) if isinstance(receipt, dict) else {}
    )
    if not row:
        return {
            "workflow": str(workflow_key or ""), "status": "invalid", "valid": False,
            "gates": ["missing_receipt"], "age_seconds": None, "artifact_results": [],
        }
    gates: list[str] = []
    if workflow is None:
        gates.append("workflow_contract")
    elif str(row.get("workflow") or "") != workflow.key or str(row.get("host") or "") != workflow.host:
        gates.append("workflow_binding")
    integrity = dict(row.get("integrity") or {}) if isinstance(row.get("integrity"), dict) else {}
    if not integrity or str(row.get("receipt_id") or "") != stable_receipt_digest(integrity):
        gates.append("receipt_integrity")
    if str(integrity.get("schema") or "") != WORKFLOW_RECEIPT_SCHEMA:
        gates.append("receipt_schema")
    binding_fields = (
        "checked_at", "workflow", "host", "session_port", "status", "steps", "artifacts",
        "readback_complete", "artifact_readback_complete", "parity_results",
        "parity_readback_complete", "missing_gates", "errors", "environment_fingerprint",
        "bridge_implementation", "workflow_contract_digest",
    )
    if integrity and any(_workflow_json_value(row.get(name)) != _workflow_json_value(integrity.get(name)) for name in binding_fields):
        gates.append("receipt_binding")
    if row.get("status") != "verified":
        gates.append("receipt_status")
    if row.get("session_port") in (None, ""):
        gates.append("pinned_session_receipt")
    if row.get("missing_gates") or row.get("errors"):
        gates.append("workflow_execution_gates")
    if not row.get("readback_complete"):
        gates.append("workflow_readback")
    if not row.get("artifact_readback_complete"):
        gates.append("artifact_readback")
    if not row.get("parity_readback_complete"):
        gates.append("parity_readback")
    if workflow is not None:
        expected_operations = [step.operation for step in workflow.steps]
        actual_operations = [str(step.get("operation") or "") for step in row.get("steps") or [] if isinstance(step, dict)]
        if actual_operations != expected_operations or not all(
            isinstance(step, dict) and step.get("ok") is True for step in row.get("steps") or []
        ):
            gates.append("workflow_step_readback")
        parity = dict(row.get("parity_results") or {})
        if not all(parity.get(check) is True for check in workflow.parity_checks):
            gates.append("workflow_parity_contract")
        current_contract_digest = stable_receipt_digest(asdict(workflow))
        if str(row.get("workflow_contract_digest") or "") != current_contract_digest:
            gates.append("workflow_contract_changed")
    if str(row.get("environment_fingerprint") or "") != receipt_environment_fingerprint():
        gates.append("receipt_environment")

    checked_at = parse_receipt_datetime(row.get("checked_at"))
    current_time = now.astimezone(timezone.utc) if isinstance(now, datetime) else datetime.now(timezone.utc)
    age_seconds: float | None = None
    if checked_at is None:
        gates.append("receipt_timestamp")
    else:
        age_seconds = (current_time - checked_at).total_seconds()
        if age_seconds < -300.0 or age_seconds > max(1.0, float(max_age_seconds)):
            gates.append("receipt_freshness")

    if integrity:
        try:
            target = bridge if bridge is not None else bridge_for_host(str(row.get("host") or ""))
            if bridge_implementation_fingerprint(target) != row.get("bridge_implementation"):
                gates.append("bridge_implementation_changed")
        except Exception:
            gates.append("bridge_implementation_unavailable")

    artifact_results: list[dict[str, Any]] = []
    for artifact in row.get("artifacts") or []:
        if not isinstance(artifact, dict):
            gates.append("artifact_receipt")
            continue
        saved = artifact.get("fingerprint") if isinstance(artifact.get("fingerprint"), dict) else {}
        current = source_file_fingerprint(str(artifact.get("path") or "")) if check_artifacts else saved
        artifact_results.append({"path": str(artifact.get("path") or ""), "saved": saved, "current": current})
        if check_artifacts and (not current.get("exists") or current != saved):
            gates.append("artifact_revision_changed")

    unique_gates = sorted(set(gates))
    return {
        "workflow": str(workflow_key or ""),
        "host": str(row.get("host") or ""),
        "status": "valid" if not unique_gates else "invalid",
        "valid": not unique_gates,
        "gates": unique_gates,
        "receipt_id": str(row.get("receipt_id") or ""),
        "session_port": row.get("session_port"),
        "age_seconds": age_seconds,
        "max_age_seconds": max(1.0, float(max_age_seconds)),
        "artifact_results": artifact_results,
    }


def workflow_receipt_ledger(path: str | Path | None = None) -> dict[str, Any]:
    """Load the durable workflow receipt ledger without trusting malformed rows."""
    ledger_path = Path(path) if path is not None else DEFAULT_WORKFLOW_LEDGER_PATH
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    receipts = {
        str(key): dict(value)
        for key, value in dict(data.get("receipts") or {}).items()
        if str(key) in PRODUCTION_WORKFLOWS and isinstance(value, dict)
    } if isinstance(data, dict) and data.get("schema") == WORKFLOW_LEDGER_SCHEMA else {}
    return {
        "schema": WORKFLOW_LEDGER_SCHEMA,
        "path": str(ledger_path),
        "receipts": receipts,
        "summary": {
            "workflow_count": len(PRODUCTION_WORKFLOWS),
            "recorded_workflows": len(receipts),
            "verified_workflows": sum(row.get("status") == "verified" for row in receipts.values()),
        },
    }


def store_workflow_receipt(
    receipt: DccWorkflowReceipt | dict[str, Any],
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically retain the latest receipt for a workflow for launch audits."""
    row = receipt.to_dict() if isinstance(receipt, DccWorkflowReceipt) else dict(receipt)
    workflow_key = str(row.get("workflow") or "")
    if workflow_key not in PRODUCTION_WORKFLOWS:
        raise ValueError("A workflow receipt must identify a registered production workflow.")
    ledger_path = Path(path) if path is not None else DEFAULT_WORKFLOW_LEDGER_PATH
    ledger = workflow_receipt_ledger(ledger_path)
    receipts = dict(ledger["receipts"])
    receipts[workflow_key] = row
    payload = {"schema": WORKFLOW_LEDGER_SCHEMA, "receipts": receipts}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=ledger_path.name + ".", suffix=".tmp", dir=str(ledger_path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(temp_name).replace(ledger_path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return workflow_receipt_ledger(ledger_path)


def _workflow_json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_workflow_json_value(item) for item in value]
    if isinstance(value, list):
        return [_workflow_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _workflow_json_value(item) for key, item in value.items()}
    return value


def resolve_workflow_session_port(host: str, requested_port: int | None = None) -> int | None:
    if requested_port is not None:
        return int(requested_port)
    preferred = preferred_session_port(host)
    if preferred is not None:
        return int(preferred)
    bridge = bridge_for_host(host)
    ports = list(bridge.find_ports()) if callable(getattr(bridge, "find_ports", None)) else []
    if len(ports) > 1:
        raise RuntimeError(
            f"Multiple {host} sessions are available ({', '.join(str(port) for port in ports)}); "
            "select a session before running this workflow."
        )
    return int(ports[0]) if ports else None


def attach_workflow_receipt_to_scene(
    document: FederatedSceneDocument,
    receipt: DccWorkflowReceipt | dict[str, Any],
    *,
    source_path: str = "",
    session_key: str = "",
    executable_hint: str = "",
) -> dict[str, Any]:
    payload = receipt.to_dict() if isinstance(receipt, DccWorkflowReceipt) else dict(receipt)
    workflow_key = str(payload.get("workflow") or "")
    workflow = PRODUCTION_WORKFLOWS.get(workflow_key)
    if workflow is None:
        raise ValueError(f"Unknown workflow receipt: {workflow_key}")
    source = str(Path(source_path).expanduser().resolve()) if source_path else ""
    source_id = stable_scene_source_id(workflow.host, source, session_key or workflow_key)
    record = {
        "workflow": workflow_key,
        "host": workflow.host,
        "role": workflow.role,
        "receipt": payload,
        "portable_outputs": list(workflow.portable_outputs),
        "restoration_requirements": list(workflow.restoration_requirements),
        "parity_checks": list(workflow.parity_checks),
        "source_id": source_id,
        "source_path": source,
        "session_key": str(session_key or "").lower(),
        "executable_hint": str(executable_hint or ""),
    }
    document.metadata.setdefault("dcc_workflow_receipts", {})[workflow_key] = record
    if not source:
        return record
    source_record = {
        "source_id": source_id,
        "provider": workflow.host,
        "session_key": str(session_key or "").lower(),
        "source_path": source,
        "source_fingerprint": source_file_fingerprint(source),
        "executable_hint": str(executable_hint or ""),
        "reload_policy": "reconnect_or_open",
        "relaunchable": Path(source).exists(),
        "workflow": workflow_key,
        "portable_artifacts": [dict(item) for item in payload.get("artifacts") or [] if isinstance(item, dict)],
    }
    document.sources = [
        item for item in document.sources
        if str(item.get("source_id") or "") != source_id
    ]
    document.sources.append(source_record)
    return record


def _execute_step(host: str, operation: str, callable_name: str, params: dict[str, Any], session_port: int | None) -> Any:
    return execute_pipeline_operation(
        host, operation, callable_name, params, session_port=session_port,
    )


def _resolve_workspace_tokens(value: Any, workspace: str) -> Any:
    if isinstance(value, str):
        resolved = value.replace("{workspace}", workspace)
        return str(Path(resolved)) if "{workspace}" in value else resolved
    if isinstance(value, list):
        return [_resolve_workspace_tokens(item, workspace) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_workspace_tokens(item, workspace) for item in value)
    if isinstance(value, dict):
        return {key: _resolve_workspace_tokens(item, workspace) for key, item in value.items()}
    return value


def _normalize_execution_result(raw: Any) -> tuple[bool, dict[str, Any]]:
    if isinstance(raw, tuple) and len(raw) == 2:
        ok, payload = bool(raw[0]), raw[1]
    else:
        ok, payload = True, raw
    output = dict(payload) if isinstance(payload, dict) else {"result": payload}
    if output.get("ok") is False:
        ok = False
    return ok, output


__all__ = [
    "DEFAULT_WORKFLOW_LEDGER_PATH", "DEFAULT_WORKFLOW_RECEIPT_MAX_AGE_SECONDS", "DccProductionWorkflow", "DccWorkflowReceipt", "DccWorkflowStep",
    "PRODUCTION_WORKFLOWS", "WORKFLOW_LEDGER_SCHEMA", "WORKFLOW_RECEIPT_SCHEMA", "WORKFLOW_SCHEMA",
    "attach_workflow_receipt_to_scene", "execute_dcc_workflow", "plan_dcc_workflow",
    "resolve_workflow_session_port", "store_workflow_receipt", "validate_workflow_catalog", "validate_workflow_receipt", "workflow_receipt_ledger",
]
