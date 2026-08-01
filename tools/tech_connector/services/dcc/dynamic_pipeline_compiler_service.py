from __future__ import annotations

"""Compile arbitrary ordered host transfers from typed operation contracts."""

from pathlib import Path
import re
from typing import Any

from reasoning_runtime.action.action_graph_service import ActionGraph, validate_action_graph
from tech_connector.services.dcc.operation_contract_service import (
    OperationContract,
    operation_contracts,
)


_HOST_ALIASES = {
    "maya": "maya",
    "blender": "blender",
    "unreal": "unreal",
    "unreal engine": "unreal",
    "motionbuilder": "motionbuilder",
    "motion builder": "motionbuilder",
    "houdini": "houdini",
    "substance painter": "substance_painter",
    "substance_painter": "substance_painter",
    "unity": "unity",
}


def extract_ordered_hosts(prompt: str) -> list[str]:
    lower = str(prompt or "").lower()
    hits: list[tuple[int, int, str]] = []
    for alias, host in _HOST_ALIASES.items():
        for match in re.finditer(rf"\b{re.escape(alias)}\b", lower):
            hits.append((match.start(), -len(alias), host))
    hosts = []
    for _position, _specificity, host in sorted(hits):
        if not hosts or hosts[-1] != host:
            hosts.append(host)
    # Repeated mentions in later explanatory clauses should not create a loop.
    deduplicated = []
    for host in hosts:
        if host not in deduplicated:
            deduplicated.append(host)
    return deduplicated


def infer_pipeline_format(prompt: str) -> str:
    lower = str(prompt or "").lower()
    if re.search(r"\b(usd|usda|usdc)\b", lower):
        return "usd"
    if re.search(r"\b(abc|alembic)\b", lower):
        return "abc"
    if re.search(r"\b(texture|textures|texture set)\b", lower):
        return "textures"
    return "fbx"


def infer_pipeline_subject(prompt: str) -> str:
    lower = str(prompt or "").lower()
    if re.search(r"\b(skeletal|skinned|rigged (?:character|mesh|proxy)|skeleton mesh)\b", lower):
        return "skeletal_mesh"
    if re.search(r"\b(animation|animate|anim|mocap|root motion|retarget|take)\b", lower):
        return "animation"
    if re.search(r"\b(rigged|skeleton)\b", lower):
        return "skeletal_mesh"
    if re.search(r"\b(texture|textures|material maps?)\b", lower):
        return "textures"
    if re.search(r"\b(static mesh|prop|collision|lod|mesh)\b", lower):
        return "static_mesh"
    return "asset"


def is_dynamic_transfer_request(prompt: str) -> bool:
    if len(extract_ordered_hosts(prompt)) < 2:
        return False
    return bool(
        re.search(
            r"\b("
            r"export|import|transfer|send|hand off|handoff|roundtrip|round trip|"
            r"open (?:it|the \w+|in)|bring (?:it|the \w+) into|publish|deliver"
            r")\b",
            str(prompt or "").lower(),
        )
    )


def _score_contract(contract: OperationContract, prompt: str, subject: str) -> tuple[int, str]:
    lower = str(prompt or "").lower()
    score = 0
    if contract.executable:
        score += 100
    if subject in contract.subjects:
        score += 30
    if "asset" in contract.subjects:
        score += 5
    words = {
        token
        for token in re.split(r"[^a-z0-9]+", f"{contract.operation} {contract.label}".lower())
        if len(token) > 2
    }
    score += sum(2 for token in words if token in lower)
    if contract.provider == "registered_operation":
        score += 4
    return score, contract.key


def _requested_post_import_contracts(
    prompt: str,
    *,
    host: str,
    subject: str,
) -> list[OperationContract]:
    lower = re.sub(r"[^a-z0-9]+", " ", str(prompt or "").lower())
    prompt_tokens = {token for token in lower.split() if len(token) > 3}
    rows = []
    for contract in operation_contracts(host=host, role="post_import", subject=subject):
        description = str(contract.metadata.get("description") or "")
        operation_text = re.sub(
            r"[^a-z0-9]+",
            " ",
            f"{contract.operation} {contract.label}".lower(),
        )
        description_text = re.sub(r"[^a-z0-9]+", " ", description.lower())
        generic = {
            "animation",
            "asset",
            "assets",
            "imported",
            "pipeline",
            "unreal",
            "create",
        }
        operation_tokens = {
            token
            for token in operation_text.split()
            if len(token) > 3
            and token not in generic
        }
        description_tokens = {
            token
            for token in description_text.split()
            if len(token) > 3 and token not in generic
        }
        direct_overlap = prompt_tokens & operation_tokens
        descriptive_overlap = prompt_tokens & description_tokens
        description_words = [
            token
            for token in description_text.split()
            if len(token) > 3 and token not in generic
        ]
        shared_description_phrase = any(
            f"{left} {right}" in lower
            for left, right in zip(description_words, description_words[1:])
        )
        if direct_overlap or (len(descriptive_overlap) >= 2 and shared_description_phrase):
            rows.append(contract)
    return rows


def _operation_acquisition_gap(
    contract: OperationContract,
    prompt: str,
) -> dict[str, Any]:
    _, skeleton_path = _unreal_path_params(prompt)
    package_paths = _unreal_package_paths(prompt)
    asset_path = next(
        (
            path
            for path in package_paths
            if path.rsplit("/", 1)[-1].lower().startswith("bs_")
        ),
        "",
    )
    behavior_contract = {
        "missing_operation": contract.operation,
        "required_arguments": list(contract.required),
        "required_python_callable": contract.callable,
        "required_python_bridge_call": (
            "unreal.AIStudioBridgeLibrary.configure_blend_space"
            if contract.operation == "unreal.create_blendspace"
            else ""
        ),
        "required_result_evidence": list(contract.validation),
        "acceptance": [
            "The registered Python callable imports inside the target host.",
            "Every required reflected bridge dependency is callable.",
            "A disposable fixture exercises the requested behavior.",
            "Structured readback satisfies the operation contract.",
        ],
    }
    acquisition_steps = [
        {
            "step_id": "confirm_capability_gap",
            "action": "resolve",
            "objective": f"Confirm implementation and live evidence for {contract.operation}.",
            "read_only": True,
        },
        {
            "step_id": "validate_dcc_adapter",
            "action": "validate",
            "objective": (
                "Load the implementation in the target host and run its disposable "
                "behavior/readback fixture."
            ),
            "depends_on": ["confirm_capability_gap"],
            "read_only": True,
        },
        {
            "step_id": "replan_original_request",
            "action": "replan",
            "objective": "Resume the original request using the newly validated operation.",
            "depends_on": ["validate_dcc_adapter"],
            "read_only": True,
        },
    ]
    return {
        "kind": "operation_evidence_gap",
        "host": contract.host,
        "operation": contract.operation,
        "capability": contract.operation,
        "required_capability": contract.operation,
        "callable": contract.callable,
        "implementation_state": contract.implementation_state,
        "request_fragment": prompt,
        "reason": (
            f"`{contract.operation}` was selected semantically, but its callable "
            f"is not execution-proven ({contract.implementation_state})."
        ),
        "acquisition": {
            "strategy": "confirm_or_implement_then_resume",
            "search_order": [
                "canonical operation inventory",
                "local Python and plugin implementations",
                "reflected host API",
                "native bridge requirements",
            ],
            "required_proof": [
                "importable Python callable",
                "non-placeholder implementation body",
                *list(contract.validation),
                "disposable host validation and structured readback",
            ],
            "resume_original_request": True,
        },
        "acquisition_plan": {
            "framework": "dcc_capability_acquisition_v1",
            "status": "implementation_requires_live_evidence",
            "host": contract.host,
            "requested_operation": contract.operation,
            "original_request": prompt,
            "resume_operation": "dynamic_cross_dcc_pipeline",
            "resume_arguments": {
                "asset_path": asset_path,
                "skeleton_path": skeleton_path,
            },
            "requested_behavior_contract": behavior_contract,
            "execution_blocked": True,
            "steps": acquisition_steps,
        },
        "execution_blocked": True,
    }


def _select_contract(
    host: str,
    role: str,
    format_name: str,
    subject: str,
    prompt: str,
) -> OperationContract | None:
    candidates = operation_contracts(
        host=host,
        role=role,
        format=format_name if role in {"import", "export"} else "",
        subject=subject,
    )
    candidates = [candidate for candidate in candidates if candidate.executable]
    if not candidates:
        return None
    return max(candidates, key=lambda item: _score_contract(item, prompt, subject))


def _path_artifact(format_name: str) -> str:
    return {
        "fbx": "fbx_path",
        "usd": "usd_path",
        "abc": "abc_path",
        "textures": "texture_paths",
    }.get(format_name, "transfer_path")


def _artifact_compatible(required: str, available: str, format_name: str) -> bool:
    if required == available:
        return True
    path_names = {"transfer_path", "source_file", _path_artifact(format_name)}
    return required in path_names and available in path_names


def _input_parameter(contract: OperationContract, artifact: str, role: str) -> str:
    if contract.callable == "unreal_tools.asset_transfer_adapter.import_fbx_verified":
        return "source_file"
    if artifact == "fbx_path":
        for candidate in ("filepath", "source_file", "input_path", "fbx_path"):
            if candidate in contract.required or candidate in contract.optional:
                return candidate
    if artifact == "usd_path":
        for candidate in ("filepath", "source_file", "input_path", "usd_path"):
            if candidate in contract.required or candidate in contract.optional:
                return candidate
    if artifact == "abc_path":
        for candidate in ("filepath", "source_file", "input_path", "abc_path"):
            if candidate in contract.required or candidate in contract.optional:
                return candidate
    if artifact == "skeleton_path":
        for candidate in ("skeleton_path", "target_skeleton_path"):
            if candidate in contract.required or candidate in contract.optional:
                return candidate
    if artifact == "animation_paths" and "animation_paths" in contract.optional:
        return "animation_paths"
    if role == "import":
        path_param = next(
            (
                item
                for item in (*contract.required, *contract.optional)
                if "path" in item or "file" in item
            ),
            "",
        )
        if path_param:
            return path_param
    if artifact in contract.required or artifact in contract.optional:
        return artifact
    return ""


def _output_parameter(contract: OperationContract) -> str:
    for candidate in ("export_path", "output_path", "filepath"):
        if candidate in contract.required or candidate in contract.optional:
            return candidate
    return ""


def _safe_stage_name(index: int, contract: OperationContract) -> str:
    operation = re.sub(r"[^a-zA-Z0-9_]+", "_", contract.operation).strip("_")
    return f"stage_{index:02d}_{contract.host}_{operation}"


def _explicit_transfer_paths(prompt: str, format_name: str) -> list[str]:
    extension = {"fbx": "fbx", "usd": "usd[ac]?", "abc": "abc"}.get(format_name)
    if not extension:
        return []
    pattern = rf"(?<![\w])([A-Za-z]:[\\/][^,\n;]+?\.{extension})\b"
    return [match.replace("\\", "/").strip() for match in re.findall(pattern, prompt, re.IGNORECASE)]


def _unreal_package_paths(prompt: str) -> list[str]:
    return [
        match.rstrip(".,;:)")
        for match in re.findall(r"(?<!\w)(/Game/[A-Za-z0-9_./-]+)", str(prompt or ""))
    ]


def _unreal_path_params(prompt: str) -> tuple[str, str]:
    package_paths = _unreal_package_paths(prompt)
    skeleton_path = ""
    for path in package_paths:
        before = str(prompt or "").lower().split(path.lower(), 1)[0][-48:]
        leaf = path.rsplit("/", 1)[-1].lower()
        if "skeleton" in before or leaf.startswith(("sk_", "skeleton_")):
            skeleton_path = path
            break
    destination_path = ""
    for path in package_paths:
        if path == skeleton_path:
            continue
        before = str(prompt or "").lower().split(path.lower(), 1)[0][-32:]
        if re.search(r"\b(into|under|destination|folder|path)\s*$", before):
            destination_path = path
            break
    if not destination_path:
        destination_path = next((path for path in package_paths if path != skeleton_path), "")
    return destination_path, skeleton_path


def _apply_prompt_parameters(
    contract: OperationContract,
    params: dict[str, Any],
    prompt: str,
) -> None:
    lower = str(prompt or "").lower()
    if contract.operation == "blender.clean_animation":
        match = re.search(
            r"\b(?:frames?|frame\s+range)\s*(\d+)\s*(?:-|to|through)\s*(\d+)\b",
            lower,
        )
        if match:
            params["frame_range"] = [int(match.group(1)), int(match.group(2))]
    if contract.operation == "unreal.create_blendspace":
        package_paths = _unreal_package_paths(prompt)
        asset_path = next(
            (
                path
                for path in package_paths
                if path.rsplit("/", 1)[-1].lower().startswith("bs_")
                or "blendspace" in lower.split(path.lower(), 1)[0][-64:]
            ),
            "",
        )
        if asset_path:
            params["asset_path"] = asset_path
    if contract.operation == "pipeline.process_meshes_for_transfer":
        params["clean_names"] = bool(re.search(r"\b(clean|rename|sanitize).{0,20}\bname", lower))
        params["apply_transforms"] = bool(
            re.search(r"\b(apply|freeze).{0,20}\btransform", lower)
        )
        lod_numbers = [int(value) for value in re.findall(r"\blod\s*(\d+)\b", lower)]
        params["lod_count"] = max(lod_numbers, default=0)
        params["ensure_material_slots"] = bool(
            re.search(r"\b(material|material slot)", lower)
        )
        params["create_collision"] = bool(
            re.search(r"\b(collision|ucx|collider)\b", lower)
        )


def _context_sensitive_parameter(name: str) -> bool:
    normalized = str(name or "").lower()
    return any(
        token in normalized
        for token in (
            "path",
            "file",
            "folder",
            "directory",
            "selection",
            "selected",
            "object",
            "mesh",
            "armature",
            "skeleton",
            "action",
            "scene",
            "frame",
            "range",
            "target",
            "source",
        )
    )


def _required_setting(
    required_inputs: list[dict[str, str]],
    *,
    action_id: str,
    contract: OperationContract,
    parameter: str,
) -> None:
    if any(
        row.get("stage") == action_id and row.get("argument") == parameter
        for row in required_inputs
    ):
        return
    required_inputs.append(
        {
            "stage": action_id,
            "host": contract.host,
            "argument": parameter,
            "question": f"What should `{parameter}` use for {contract.label}?",
        }
    )


def compile_dynamic_pipeline(
    prompt: str,
    *,
    project_root: str | None = None,
    use_default_settings: bool = True,
    custom_settings: dict[str, Any] | None = None,
    requirement_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = extract_ordered_hosts(prompt)
    format_name = infer_pipeline_format(prompt)
    subject = infer_pipeline_subject(prompt)
    if len(hosts) < 2:
        return {
            "success": False,
            "framework": "dynamic_typed_pipeline_v1",
            "hosts": hosts,
            "format": format_name,
            "subject": subject,
            "gaps": [
                {
                    "kind": "missing_host_sequence",
                    "message": "A transfer pipeline needs at least two ordered host applications.",
                }
            ],
        }

    selected: list[OperationContract] = []
    gaps: list[dict[str, Any]] = []
    prepare_requested = bool(
        re.search(
            r"\b(create|build|generate|make)\b.{0,48}\b(rig|rigged|proxy|fixture)\b",
            str(prompt or "").lower(),
        )
    )
    if prepare_requested:
        preparers = operation_contracts(
            host=hosts[0],
            role="prepare",
            subject=subject,
        )
        preparers = [contract for contract in preparers if contract.executable]
        if preparers:
            selected.append(
                max(
                    preparers,
                    key=lambda item: _score_contract(item, prompt, subject),
                )
            )
        else:
            gaps.append(
                {
                    "kind": "missing_requested_operation",
                    "host": hosts[0],
                    "role": "prepare",
                    "subject": subject,
                    "message": (
                        f"The prompt requests source preparation in {hosts[0]}, but no "
                        "verified preparation operation matches it."
                    ),
                }
            )
    process_requested = bool(
        re.search(
            r"\b(clean|process|bake|retarget|optimi[sz]e|rename|transform|"
            r"collision|collider|lod|material)\b",
            str(prompt or "").lower(),
        )
    )
    if process_requested:
        source_processor = _select_contract(
            hosts[0], "process", format_name, subject, prompt
        )
        if source_processor:
            selected.append(source_processor)
    exporter = _select_contract(hosts[0], "export", format_name, subject, prompt)
    if not exporter:
        gaps.append(
            {
                "kind": "missing_transfer_edge",
                "host": hosts[0],
                "role": "export",
                "format": format_name,
                "subject": subject,
                "message": f"No verified {format_name} exporter for {subject} is callable in {hosts[0]}.",
            }
        )
    else:
        selected.append(exporter)

    for index, host in enumerate(hosts[1:], start=1):
        importer = _select_contract(host, "import", format_name, subject, prompt)
        if not importer:
            gaps.append(
                {
                    "kind": "missing_transfer_edge",
                    "host": host,
                    "role": "import",
                    "format": format_name,
                    "subject": subject,
                    "from_host": hosts[index - 1],
                    "message": f"No verified {format_name} importer for {subject} is callable in {host}.",
                }
            )
            continue
        selected.append(importer)

        is_final = index == len(hosts) - 1
        if not is_final and process_requested:
            processor = _select_contract(host, "process", format_name, subject, prompt)
            if processor:
                selected.append(processor)
        if not is_final:
            exporter = _select_contract(host, "export", format_name, subject, prompt)
            if not exporter:
                gaps.append(
                    {
                        "kind": "missing_transfer_edge",
                        "host": host,
                        "role": "export",
                        "format": format_name,
                        "subject": subject,
                        "message": f"No verified {format_name} exporter for intermediate host {host}.",
                    }
                )
            else:
                selected.append(exporter)

    post_import = (
        _requested_post_import_contracts(
            prompt,
            host=hosts[-1],
            subject=subject,
        )
        if subject == "animation"
        else []
    )
    unavailable_post_import = [
        contract for contract in post_import if not contract.executable
    ]
    if unavailable_post_import:
        gaps.extend(
            _operation_acquisition_gap(contract, prompt)
            for contract in unavailable_post_import
        )
        post_import = [
            contract for contract in post_import if contract.executable
        ]
    structural_gaps = [
        gap for gap in gaps if gap.get("kind") != "operation_evidence_gap"
    ]
    if post_import and not structural_gaps:
        pending = list(post_import)
        available_outputs = {
            output
            for contract in selected
            for output in contract.produces
        }
        while pending:
            ready = [
                contract
                for contract in pending
                if all(
                    consumed in available_outputs or consumed == "skeleton_path"
                    for consumed in contract.consumes
                )
            ]
            if not ready:
                for contract in pending:
                    gaps.append(
                        {
                            "kind": "missing_typed_dependency",
                            "host": contract.host,
                            "operation": contract.operation,
                            "required_artifacts": [
                                item
                                for item in contract.consumes
                                if item not in available_outputs
                                and item != "skeleton_path"
                            ],
                            "message": (
                                f"{contract.label} was requested but its typed dependencies "
                                "could not be produced by the selected stages."
                            ),
                        }
                    )
                break
            next_phase = min(contract.phase_order for contract in ready)
            for contract in sorted(
                [
                    contract
                    for contract in ready
                    if contract.phase_order == next_phase
                ],
                key=lambda item: item.key,
            ):
                selected.append(contract)
                available_outputs.update(contract.produces)
                pending.remove(contract)

    if hosts[-1] == "unreal" and not structural_gaps:
        validator = _select_contract("unreal", "validate", format_name, subject, prompt)
        if validator:
            selected.append(validator)

    if structural_gaps:
        return {
            "success": False,
            "framework": "dynamic_typed_pipeline_v1",
            "hosts": hosts,
            "format": format_name,
            "subject": subject,
            "selected_contracts": [item.to_dict() for item in selected],
            "gaps": structural_gaps,
            "capability_gaps": gaps,
        }

    graph = ActionGraph(
        goal=prompt,
        intent="dynamic_cross_dcc_pipeline",
        confidence=0.96,
        diagnostics=[
            f"Resolved ordered hosts: {' -> '.join(hosts)}",
            f"Selected {len(selected)} verified contracts for {subject} via {format_name}.",
        ],
    )
    available: dict[str, str] = {}
    implicit_source_artifacts = {
        f"{hosts[0]}_scene",
        "scene",
        "asset",
        "meshes",
        "animations",
        "skeleton",
        "substance_project",
        "houdini_geometry",
        "motionbuilder_scene",
    }
    data_edges: list[dict[str, str]] = []
    required_inputs: list[dict[str, str]] = []
    previous_action_id = ""
    stage_rows = []
    path_artifact = _path_artifact(format_name)
    explicit_paths = _explicit_transfer_paths(prompt, format_name)
    export_index = 0
    unreal_destination, unreal_skeleton = _unreal_path_params(prompt)
    settings = dict(custom_settings or {})
    custom_unreal_destination = str(settings.get("unreal_destination_path") or "").strip()
    parameter_provenance: list[dict[str, Any]] = []
    literal_artifacts = {
        "skeleton_path": unreal_skeleton,
    }

    for index, contract in enumerate(selected, start=1):
        action_id = _safe_stage_name(index, contract)
        def setting_for(parameter: str) -> Any:
            return settings.get(
                f"{contract.host}.{contract.operation}.{parameter}",
                settings.get(parameter),
            )

        params = dict(contract.optional)
        _apply_prompt_parameters(contract, params, prompt)
        consumed_bindings = {}
        for consumed in contract.consumes:
            source_artifact = next(
                (
                    artifact
                    for artifact in reversed(list(available))
                    if _artifact_compatible(consumed, artifact, format_name)
                ),
                "",
            )
            if source_artifact:
                parameter = _input_parameter(contract, consumed, contract.role)
                if parameter:
                    params[parameter] = f"${source_artifact}"
                    consumed_bindings[parameter] = source_artifact
                    data_edges.append(
                        {
                            "from": available[source_artifact],
                            "output": source_artifact,
                            "to": action_id,
                            "input": parameter,
                        }
                    )
            elif literal_artifacts.get(consumed):
                parameter = _input_parameter(contract, consumed, contract.role)
                if parameter:
                    params[parameter] = literal_artifacts[consumed]
                    consumed_bindings[parameter] = consumed
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": parameter,
                            "value": literal_artifacts[consumed],
                            "source": "user_prompt",
                            "resolution": "",
                        }
                    )
            elif (
                consumed not in implicit_source_artifacts
                and consumed not in {"destination_path"}
                and consumed != "skeleton_path"
                and contract.role != "export"
            ):
                required_inputs.append(
                    {
                        "stage": action_id,
                        "host": contract.host,
                        "argument": consumed,
                        "question": f"What value should `{consumed}` use for {contract.label}?",
                    }
                )

        if contract.role == "export":
            output_parameter = _output_parameter(contract)
            if output_parameter:
                if export_index < len(explicit_paths):
                    params[output_parameter] = explicit_paths[export_index]
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": output_parameter,
                            "value": params[output_parameter],
                            "source": "user_prompt",
                            "resolution": "",
                        }
                    )
                elif setting_for(output_parameter) not in (None, ""):
                    params[output_parameter] = setting_for(output_parameter)
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": output_parameter,
                            "value": params[output_parameter],
                            "source": "user_setting",
                            "resolution": "",
                        }
                    )
                elif not use_default_settings:
                    params[output_parameter] = ""
                    _required_setting(
                        required_inputs,
                        action_id=action_id,
                        contract=contract,
                        parameter=output_parameter,
                    )
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": output_parameter,
                            "value": "",
                            "source": "required_user_input",
                            "resolution": "",
                        }
                    )
                else:
                    suffix = {"fbx": ".fbx", "usd": ".usd", "abc": ".abc"}.get(
                        format_name, ""
                    )
                    params[output_parameter] = str(
                        Path("${pipeline_workspace}") / f"{action_id}{suffix}"
                    ).replace("\\", "/")
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": output_parameter,
                            "value": params[output_parameter],
                            "source": "generated_pipeline_workspace",
                            "resolution": (
                                f"{contract.label} writes `{output_parameter}` under the "
                                "pipeline's disposable workspace."
                            ),
                        }
                    )
                export_index += 1
        if contract.host == "unreal" and contract.role == "import":
            params["subject"] = subject
            if unreal_destination:
                params["destination_path"] = unreal_destination
                destination_source = "user_prompt"
            elif not use_default_settings and (
                custom_unreal_destination or setting_for("destination_path")
            ):
                params["destination_path"] = (
                    custom_unreal_destination or setting_for("destination_path")
                )
                destination_source = "user_setting"
            elif use_default_settings:
                params["destination_path"] = "__CURRENT_CONTENT_BROWSER__"
                destination_source = "current_content_browser_at_execution"
            else:
                params["destination_path"] = ""
                destination_source = "required_user_input"
                required_inputs.append(
                    {
                        "stage": action_id,
                        "host": "unreal",
                        "argument": "destination_path",
                        "question": "Which Unreal Content Browser folder should receive the imported assets?",
                    }
                )
            parameter_provenance.append(
                {
                    "stage": action_id,
                    "parameter": "destination_path",
                    "value": params["destination_path"],
                    "source": destination_source,
                    "resolution": (
                        "Uses the selected/current Content Browser folder when execution starts; "
                        "falls back to /Game/AIStudio/Imports if Unreal reports no current folder."
                        if destination_source == "current_content_browser_at_execution"
                        else ""
                    ),
                }
            )
            if unreal_skeleton or setting_for("skeleton_path"):
                params["skeleton_path"] = (
                    unreal_skeleton or setting_for("skeleton_path")
                )
            if subject == "animation" and not params.get("skeleton_path"):
                _required_setting(
                    required_inputs,
                    action_id=action_id,
                    contract=contract,
                    parameter="skeleton_path",
                )
                required_inputs[-1][
                    "question"
                ] = "Which target Unreal Skeleton should receive the imported animation?"

        if not use_default_settings:
            for parameter, default_value in contract.optional.items():
                if not _context_sensitive_parameter(parameter):
                    continue
                if isinstance(params.get(parameter), str) and params[parameter].startswith("$"):
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": parameter,
                            "value": params[parameter],
                            "source": "upstream_data_binding",
                            "resolution": "",
                        }
                    )
                    continue
                setting_key = f"{contract.host}.{contract.operation}.{parameter}"
                supplied = settings.get(setting_key, settings.get(parameter))
                if supplied not in (None, "", [], {}):
                    params[parameter] = supplied
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": parameter,
                            "value": supplied,
                            "source": "user_setting",
                            "resolution": "",
                        }
                    )
                    continue
                if params.get(parameter) != default_value:
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": parameter,
                            "value": params.get(parameter),
                            "source": "user_prompt_or_derived",
                            "resolution": "",
                        }
                    )
                    continue
                parameter_provenance.append(
                    {
                        "stage": action_id,
                        "parameter": parameter,
                        "value": default_value,
                        "source": "registered_function_default",
                        "resolution": (
                            f"{contract.label} declares `{parameter}`={default_value!r}; "
                            "this is the callable's own default, not a planner assumption."
                        ),
                    }
                )
        else:
            for parameter, default_value in contract.optional.items():
                if not _context_sensitive_parameter(parameter):
                    continue
                if any(
                    row.get("stage") == action_id and row.get("parameter") == parameter
                    for row in parameter_provenance
                ):
                    continue
                parameter_provenance.append(
                    {
                        "stage": action_id,
                        "parameter": parameter,
                        "value": params.get(parameter, default_value),
                        "source": (
                            "upstream_data_binding"
                            if isinstance(params.get(parameter), str)
                            and params[parameter].startswith("$")
                            else "operation_default"
                        ),
                        "resolution": (
                            f"{contract.label} uses its registered default for `{parameter}`: "
                            f"{params.get(parameter, default_value)!r}."
                        ),
                    }
                )

        for required_parameter in contract.required:
            if params.get(required_parameter) not in (None, "", [], {}):
                continue
            _required_setting(
                required_inputs,
                action_id=action_id,
                contract=contract,
                parameter=required_parameter,
            )

        action = graph.add(
            "execute_dcc",
            {
                "host": contract.host,
                "operation": contract.operation,
                "callable": contract.callable,
                "params": params,
                "operation_contract": contract.to_dict(),
                "produces": list(contract.produces),
                "consumes": list(contract.consumes),
                "validation": list(contract.validation),
                "rollback": list(contract.rollback),
            },
            depends_on=[previous_action_id] if previous_action_id else [],
            id=action_id,
            title=contract.label,
            requires_approval=contract.mutates_project,
        )
        previous_action_id = action.id
        for produced in contract.produces:
            available[produced] = action_id
        if contract.role == "export" and path_artifact not in contract.produces:
            available[path_artifact] = action_id
        stage_rows.append(
            {
                "id": action_id,
                "host": contract.host,
                "role": contract.role,
                "operation": contract.operation,
                "callable": contract.callable,
                "params": params,
                "consumed_bindings": consumed_bindings,
                "produces": list(contract.produces),
                "validation": list(contract.validation),
                "rollback": list(contract.rollback),
                "implementation_state": contract.implementation_state,
                "evidence": {
                    "level": contract.metadata.get(
                        "evidence_level",
                        "registered_callable",
                    ),
                    "live_validated": bool(
                        contract.metadata.get("live_validated", False)
                    ),
                    "implementation": list(
                        contract.metadata.get("implementation_evidence") or []
                    ),
                    "validation_receipt": dict(
                        contract.metadata.get("validation_receipt") or {}
                    ),
                },
            }
        )

    data = graph.to_dict()
    assumption_messages = [
        row["resolution"]
        for row in parameter_provenance
        if row.get("resolution")
    ]
    if assumption_messages:
        data.setdefault("diagnostics", []).extend(assumption_messages)
    evidence_rows = [
        {
            "stage": row["id"],
            "host": row["host"],
            "operation": row["operation"],
            "level": row["evidence"]["level"],
            "live_validated": row["evidence"]["live_validated"],
        }
        for row in stage_rows
    ]
    data.update(
        {
            "framework": "dynamic_typed_pipeline_v1",
            "success": not required_inputs and not gaps,
            "execution_ready": not required_inputs and not gaps,
            "hosts": hosts,
            "format": format_name,
            "subject": subject,
            "stages": stage_rows,
            "data_edges": data_edges,
            "required_inputs": required_inputs,
            "use_default_settings": bool(use_default_settings),
            "parameter_provenance": parameter_provenance,
            "assumptions": assumption_messages,
            "selected_contracts": [item.to_dict() for item in selected],
            "evidence_summary": {
                "stage_count": len(evidence_rows),
                "live_validated_count": sum(
                    bool(row["live_validated"]) for row in evidence_rows
                ),
                "not_live_validated_count": sum(
                    not bool(row["live_validated"]) for row in evidence_rows
                ),
                "stages": evidence_rows,
                "claim": (
                    "Execution-ready means callables, arguments, and typed dependencies "
                    "are resolved. Only stages marked live_validated have durable disposable "
                    "host-fixture proof."
                ),
            },
            "gaps": gaps,
            "capability_gaps": gaps,
        }
    )
    data["validation"] = validate_action_graph(data)
    from tech_connector.services.dcc.pipeline_requirement_coverage_service import (
        build_pipeline_requirement_ledger,
    )

    data["requirement_ledger"] = build_pipeline_requirement_ledger(
        prompt,
        stage_rows,
        requirement_manifest=requirement_manifest,
    )
    data["requirement_manifest"] = dict(requirement_manifest or {})
    return data
