from __future__ import annotations

"""Compile arbitrary ordered host transfers from typed operation contracts."""

from pathlib import Path
import re
from typing import Any

from reasoning_runtime.action.action_graph_service import ActionGraph, validate_action_graph
from tech_connector.game_engine.integration.operation_contract_service import (
    OperationContract,
    operation_contracts,
    resolve_operation_contract,
)


_HOST_ALIASES = {
    "maya": "maya",
    "blender": "blender",
    "unreal": "unreal",
    "unreal engine": "unreal",
    "motionbuilder": "motionbuilder",
    "motion builder": "motionbuilder",
    "houdini": "houdini",
    "3ds max": "3dsmax",
    "3dsmax": "3dsmax",
    "max": "3dsmax",
    "substance painter": "substance_painter",
    "substance_painter": "substance_painter",
    "unity": "unity",
    "tech connector engine": "tech_connector",
    "tech connector": "tech_connector",
    "tc engine": "tech_connector",
    "our engine": "tech_connector",
}


def extract_explicit_operation_mentions(
    prompt: str,
    hosts: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve every explicitly named operation/callable and report unresolved names."""
    text = str(prompt or "")
    lower = text.casefold()
    host_order = list(hosts or extract_ordered_hosts(text))
    contracts = [
        contract
        for host in host_order
        for contract in operation_contracts(host=host)
    ]
    matches: list[tuple[int, OperationContract, str]] = []
    matched_tokens: set[str] = set()
    for contract in contracts:
        names = (contract.callable, contract.operation, f"{contract.host}.{contract.operation}")
        found: list[tuple[int, str]] = []
        for name in names:
            candidate = str(name or "").casefold()
            if "." not in candidate:
                continue
            position = lower.find(candidate)
            if position >= 0:
                found.append((position, name))
        if found:
            position, requested_name = min(found, key=lambda item: item[0])
            matches.append((position, contract, requested_name))
            matched_tokens.add(str(requested_name).casefold())

    named_list_cue = bool(re.search(r"\b(?:functions?|operations?|calls?)\s*(?::|are|=)", lower))
    quoted = {
        value.casefold()
        for value in re.findall(r"[`'\"]([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)[`'\"]", text)
    }
    dotted_values = {
        value.casefold(): value
        for value in re.findall(r"(?<![/\w])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)(?![/\w])", text)
    }
    dotted = set(dotted_values)
    known_names = {
        str(name).casefold()
        for contract in contracts
        for name in (contract.operation, contract.callable, f"{contract.host}.{contract.operation}")
    }
    ignored_suffixes = {"fbx", "usd", "usda", "usdc", "abc", "png", "jpg", "jpeg", "tga", "exr"}
    for token in sorted(dotted - known_names):
        if token.rsplit(".", 1)[-1] in ignored_suffixes:
            continue
        for host in host_order:
            requested_token = dotted_values[token]
            resolution = resolve_operation_contract(requested_token, host=host)
            payload = dict(resolution.get("contract") or {}) if resolution.get("ok") else {}
            if not payload:
                continue
            payload.pop("executable", None)
            try:
                contract = OperationContract(**payload)
            except (TypeError, ValueError):
                continue
            matches.append((lower.find(token), contract, requested_token))
            matched_tokens.add(token)
            known_names.update(
                {
                    contract.operation.casefold(),
                    contract.callable.casefold(),
                    f"{contract.host}.{contract.operation}".casefold(),
                }
            )
            break
    resolved_keys = set()
    resolved = []
    for position, contract, requested_name in sorted(matches, key=lambda item: (item[0], item[1].key)):
        if contract.key in resolved_keys:
            continue
        resolved_keys.add(contract.key)
        resolved.append({"position": position, "requested_name": requested_name, "contract": contract})
    unresolved = sorted(
        token
        for token in dotted
        if token not in known_names
        and token not in matched_tokens
        and token.rsplit(".", 1)[-1] not in ignored_suffixes
        and (named_list_cue or token in quoted)
    )
    return resolved, unresolved


def _merge_explicit_contracts(
    selected: list[OperationContract],
    mentions: list[dict[str, Any]],
    hosts: list[str],
) -> list[OperationContract]:
    if not mentions:
        return selected
    explicit = [row["contract"] for row in mentions]
    explicit_keys = {contract.key for contract in explicit}
    replaceable_roles = {"prepare", "import", "process", "export", "validate"}
    explicit_host_roles = {
        (contract.host, contract.role)
        for contract in explicit
        if contract.role in replaceable_roles
    }
    combined = [
        contract
        for contract in selected
        if contract.key in explicit_keys
        or (contract.host, contract.role) not in explicit_host_roles
    ]
    existing = {contract.key for contract in combined}
    combined.extend(contract for contract in explicit if contract.key not in existing)
    positions = {row["contract"].key: int(row["position"]) for row in mentions}
    role_order = {
        "prepare": 0, "resolve": 5, "import": 10, "process": 20,
        "operate": 25, "export": 30, "author": 40, "post_import": 45,
        "validate": 50,
    }
    host_positions = {host: index for index, host in enumerate(hosts)}
    return sorted(
        combined,
        key=lambda contract: (
            host_positions.get(contract.host, len(hosts)),
            (
                1
                if contract.key in positions
                else 0
                if role_order.get(contract.role, 25) <= 20
                else 2
            ),
            (
                positions[contract.key]
                if contract.key in positions
                else role_order.get(contract.role, 25)
            ),
            contract.phase_order,
            contract.key,
        ),
    )


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
    if required in path_names and available in path_names:
        return True
    object_sets = {
        "export_objects", "objects", "selection", "meshes", "nodes",
    }
    return required in object_sets and available in object_sets


def _best_available_artifact(
    required: str,
    available: dict[str, str],
    format_name: str,
) -> str:
    compatible = [
        artifact
        for artifact in available
        if _artifact_compatible(required, artifact, format_name)
    ]
    if not compatible:
        return ""
    object_priority = {
        "export_objects": 0,
        "objects": 1,
        "selection": 2,
        "nodes": 3,
        "meshes": 4,
    }
    positions = {artifact: index for index, artifact in enumerate(available)}
    return min(
        compatible,
        key=lambda artifact: (
            0 if artifact == required else 1,
            object_priority.get(artifact, 50),
            -positions.get(artifact, 0),
        ),
    )


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
    if artifact in {"export_objects", "objects", "selection", "meshes", "nodes"}:
        for candidate in ("selection", "object_names", "objects", "nodes"):
            if candidate in contract.required or candidate in contract.optional:
                return candidate
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


def infer_dcc_export_scope(prompt: str, *, host: str, subject: str) -> dict[str, Any]:
    """Describe the host objects a DCC stage should resolve at execution time."""

    lower = str(prompt or "").lower()
    explicit_scene = bool(re.search(
        r"\b(?:whole|entire|full)\s+scene\b|\ball\s+(?:scene\s+)?objects\b",
        lower,
    ))
    explicit_selected_only = bool(re.search(
        r"\b(?:only\s+)?(?:the\s+)?selected\s+(?:objects?|items?)\b|"
        r"\bexport\s+(?:only\s+)?(?:the\s+)?selection\b",
        lower,
    ))
    rig_intent = subject in {"animation", "skeletal_mesh"} or bool(re.search(
        r"\b(rig|rigged|character|armature|skeleton|skinned|animation|mocap)\b",
        lower,
    ))
    if explicit_scene:
        scope = "scene_contents"
        label = "Whole scene contents"
    elif explicit_selected_only:
        scope = "current_selection"
        label = "Current selection only"
    elif rig_intent:
        scope = "rig_contents"
        label = "Rig, skinned meshes, and export children"
    elif subject == "static_mesh":
        scope = "selected_or_scene_meshes"
        label = "Selected meshes, or scene meshes when nothing is selected"
    else:
        scope = "current_selection_or_subject"
        label = "Current selection, with a subject-aware scene fallback"
    return {
        "$pipeline_context": "dcc_export_scope_v1",
        "host": str(host or ""),
        "scope": scope,
        "subject": str(subject or "asset"),
        "label": label,
    }


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
            "project_root": str(project_root or ""),
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
    explicit_mentions, unresolved_function_names = extract_explicit_operation_mentions(prompt, hosts)
    gaps: list[dict[str, Any]] = [
        {
            "kind": "unknown_requested_function",
            "function": name,
            "message": f"The explicitly requested function `{name}` is not registered for the named hosts.",
            "execution_blocked": True,
        }
        for name in unresolved_function_names
    ]
    unavailable_explicit = [
        row for row in explicit_mentions if not row["contract"].executable
    ]
    gaps.extend(
        _operation_acquisition_gap(row["contract"], prompt)
        for row in unavailable_explicit
    )
    executable_explicit_mentions = [
        row for row in explicit_mentions if row["contract"].executable
    ]
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

    selected = _merge_explicit_contracts(selected, executable_explicit_mentions, hosts)
    structural_gaps = [
        gap for gap in gaps if gap.get("kind") != "operation_evidence_gap"
    ]
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
            "explicit_function_requests": [
                {
                    "requested_name": row["requested_name"],
                    "host": row["contract"].host,
                    "operation": row["contract"].operation,
                    "resolved": row["contract"].executable,
                }
                for row in explicit_mentions
            ],
            "unresolved_function_requests": unresolved_function_names,
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
    artifact_literals: dict[str, Any] = {}
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
        "objects",
        "export_objects",
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
        stage_produces = list(contract.produces)
        if contract.role == "export":
            stage_produces = [
                path_artifact if produced == "transfer_path" else produced
                for produced in stage_produces
            ]
            if path_artifact not in stage_produces:
                stage_produces.append(path_artifact)
        def setting_for(parameter: str) -> Any:
            return settings.get(
                f"{contract.host}.{contract.operation}.{parameter}",
                settings.get(parameter),
            )

        params = dict(contract.optional)
        _apply_prompt_parameters(contract, params, prompt)
        for optional_parameter in contract.optional:
            supplied = setting_for(optional_parameter)
            if supplied in (None, "", [], {}):
                continue
            params[optional_parameter] = supplied
            parameter_provenance.append(
                {
                    "stage": action_id,
                    "parameter": optional_parameter,
                    "value": supplied,
                    "source": "user_setting",
                    "resolution": (
                        f"{contract.label} uses the explicit pipeline setting "
                        f"for `{optional_parameter}`."
                    ),
                }
            )
        consumed_bindings = {}
        for consumed in contract.consumes:
            source_artifact = _best_available_artifact(
                consumed,
                available,
                format_name,
            )
            if source_artifact:
                parameter = _input_parameter(contract, consumed, contract.role)
                if parameter:
                    params[parameter] = {
                        "from_action": available[source_artifact],
                        "result_path": source_artifact,
                    }
                    consumed_bindings[parameter] = source_artifact
                    data_edges.append(
                        {
                            "from": available[source_artifact],
                            "output": source_artifact,
                            "to": action_id,
                            "input": parameter,
                        }
                    )
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": parameter,
                            "value": params[parameter],
                            "source": "upstream_result_reference",
                            "resolution": "",
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

        context_parameter = ""
        if contract.role == "export":
            context_parameter = next(
                (
                    candidate
                    for candidate in ("selection", "object_names", "objects", "nodes")
                    if candidate in contract.required or candidate in contract.optional
                ),
                "",
            )
        elif contract.role == "process" and "objects" in contract.optional:
            context_parameter = "objects"
        if (
            context_parameter
            and context_parameter not in consumed_bindings
            and params.get(context_parameter) in (None, "", [], {})
        ):
            context_spec = infer_dcc_export_scope(
                prompt,
                host=contract.host,
                subject=subject,
            )
            params[context_parameter] = context_spec
            parameter_provenance.append(
                {
                    "stage": action_id,
                    "parameter": context_parameter,
                    "value": context_spec,
                    "source": "runtime_host_context",
                    "resolution": (
                        f"{contract.label} resolves {context_spec['label'].lower()} "
                        "from the live host when this pipeline runs."
                    ),
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
        if (
            contract.host == "unreal"
            and contract.role == "validate"
            and "registry_readback" in f"{contract.operation} {contract.callable}"
            and unreal_destination
            and not params.get("destination_path")
        ):
            params["destination_path"] = unreal_destination
            parameter_provenance.append(
                {
                    "stage": action_id,
                    "parameter": "destination_path",
                    "value": unreal_destination,
                    "source": "user_prompt",
                    "resolution": (
                        "Registry validation inherits the explicit Unreal import destination "
                        "so readback is scoped to the requested content folder."
                    ),
                }
            )
        if contract.host == "tech_connector" and contract.role == "import":
            configured_root = str(project_root or setting_for("project_root") or "").strip()
            params["project_root"] = configured_root
            if not configured_root:
                _required_setting(
                    required_inputs,
                    action_id=action_id,
                    contract=contract,
                    parameter="project_root",
                )

        if not use_default_settings:
            for parameter, default_value in contract.optional.items():
                if not _context_sensitive_parameter(parameter):
                    continue
                if any(
                    row.get("stage") == action_id and row.get("parameter") == parameter
                    for row in parameter_provenance
                ):
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
            if params.get(required_parameter) in (None, "", [], {}):
                supplied = setting_for(required_parameter)
                if supplied not in (None, "", [], {}):
                    params[required_parameter] = supplied
                    parameter_provenance.append(
                        {
                            "stage": action_id,
                            "parameter": required_parameter,
                            "value": supplied,
                            "source": "user_setting",
                            "resolution": (
                                f"{contract.label} uses the explicit pipeline setting "
                                f"for required argument `{required_parameter}`."
                            ),
                        }
                    )
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
                "produces": stage_produces,
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
        if contract.role == "export":
            output_parameter = _output_parameter(contract)
            output_value = params.get(output_parameter) if output_parameter else None
            if output_value not in (None, "", [], {}):
                for produced in stage_produces:
                    if _artifact_compatible(produced, path_artifact, format_name):
                        artifact_literals[produced] = output_value
        for produced in stage_produces:
            available[produced] = action_id
        stage_rows.append(
            {
                "id": action_id,
                "host": contract.host,
                "role": contract.role,
                "operation": contract.operation,
                "callable": contract.callable,
                "params": params,
                "consumed_bindings": consumed_bindings,
                "produces": stage_produces,
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
            "project_root": str(project_root or ""),
            "stages": stage_rows,
            "data_edges": data_edges,
            "required_inputs": required_inputs,
            "use_default_settings": bool(use_default_settings),
            "parameter_provenance": parameter_provenance,
            "assumptions": assumption_messages,
            "selected_contracts": [item.to_dict() for item in selected],
            "explicit_function_requests": [
                {
                    "requested_name": row["requested_name"],
                    "host": row["contract"].host,
                    "operation": row["contract"].operation,
                    "resolved": row["contract"].executable,
                }
                for row in explicit_mentions
            ],
            "unresolved_function_requests": unresolved_function_names,
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
    from tech_connector.game_engine.integration.pipeline_requirement_coverage_service import (
        build_pipeline_requirement_ledger,
    )

    data["requirement_ledger"] = build_pipeline_requirement_ledger(
        prompt,
        stage_rows,
        requirement_manifest=requirement_manifest,
    )
    data["requirement_manifest"] = dict(requirement_manifest or {})
    return data

