from __future__ import annotations

"""Compile arbitrary ordered host transfers from typed operation contracts."""

from pathlib import Path
import re
from typing import Any

from reasoning_runtime.action.action_graph_service import ActionGraph, validate_action_graph
from tech_connector.game_engine.integration.dcc_operation_service import (
    build_dcc_operation_params,
    is_painter_multi_operation_prompt,
)
from tech_connector.game_engine.integration.operation_contract_service import (
    OperationContract,
    operation_contracts,
    registered_operation_contract,
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
    # A texture export preset is not a destination DCC. Keep later, genuine
    # Unreal mentions (for example, "then import into Unreal") visible.
    painter_preset_spans = [
        match.span()
        for match in re.finditer(
            r"\bunreal(?:\s+packed)?\s+(?:export\s+)?preset\b|"
            r"\bunreal\s+packed\b",
            lower,
        )
    ]
    for alias, host in _HOST_ALIASES.items():
        for match in re.finditer(rf"\b{re.escape(alias)}\b", lower):
            if host == "unreal" and any(
                start <= match.start() < end for start, end in painter_preset_spans
            ):
                continue
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
    if re.search(r"\b(skeletal|skinned|skeleton mesh)\b", lower) or re.search(
        r"\brigged\b(?!\s+(?:animations?|anim|clips?)\b)", lower,
    ):
        return "skeletal_mesh"
    if re.search(r"\b(animation|animate|animated|anim|mocap|root motion|retarget|take|keyframed?)\b", lower):
        return "animation"
    if re.search(r"\b(texture|textures|material maps?)\b", lower):
        return "textures"
    if re.search(r"\b(rigged|skeleton|rig|armature|joints?|bones?|character)\b", lower):
        return "skeletal_mesh"
    if re.search(r"\b(static meshes?|props?|collision|lods?|meshes?)\b", lower):
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


def compile_delegated_painter_pipeline(prompt: str) -> dict[str, Any] | None:
    """Fail closed for a single-host Painter workflow with a manual layer step.

    The registered smart-material callable deliberately does not mutate the
    layer stack. Generic symbol discovery must not turn its return dictionary
    into a fictional producer for neighboring required arguments.
    """
    if extract_ordered_hosts(prompt) != ["substance_painter"] or not is_painter_multi_operation_prompt(prompt):
        return None

    cues = (
        ("project.create", r"\b(?:create|new|start)\b.{0,20}\bproject\b"),
        ("material.apply", r"\b(?:apply|add|assign|use)\b.{0,32}\b(?:smart\s+)?material\b"),
        ("textures.export", r"\bexport\b.{0,24}\b(?:textures?|maps?)\b"),
    )
    matches = [
        (match.start(), name)
        for name, pattern in cues
        if (match := re.search(pattern, prompt, re.IGNORECASE)) is not None
    ]
    matches.sort()
    requested = [name for _position, name in matches]
    contracts = [
        contract.to_dict()
        for name in requested
        if (contract := registered_operation_contract("substance_painter", name)) is not None
    ]
    stages = []
    required_inputs = []
    parameter_provenance = []
    for index, (position, operation) in enumerate(matches):
        clause_end = matches[index + 1][0] if index + 1 < len(matches) else len(prompt)
        clause = prompt[position:clause_end]
        contract = next(row for row in contracts if row["operation"] == operation)
        params = dict(contract["optional"])
        extracted = build_dcc_operation_params("substance_painter", operation, clause)
        params.update(extracted)
        if operation == "material.apply":
            texture_set = re.search(
                r"\btexture\s+set\s+(?:['\"]([^'\"]+)['\"]|([A-Za-z_][A-Za-z0-9_]*))",
                clause,
                re.IGNORECASE,
            )
            if texture_set:
                params["texture_set"] = texture_set.group(1) or texture_set.group(2)
                extracted["texture_set"] = params["texture_set"]
            else:
                named_texture_set = re.search(
                    r"\b(?:the\s+)?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s+texture\s+set\b",
                    clause,
                    re.IGNORECASE,
                )
                if named_texture_set:
                    params["texture_set"] = named_texture_set.group(1)
                    extracted["texture_set"] = params["texture_set"]
        if operation == "textures.export":
            preset = re.search(r"\b(?:using|with)\s+preset\s+([^.,;]+)", clause, re.IGNORECASE)
            if preset is None:
                preset = re.search(
                    r"\b(?:using|with)\s+(?:the\s+)?([^.,;]+?)\s+preset\b",
                    clause,
                    re.IGNORECASE,
                )
            if preset:
                params["preset_name"] = preset.group(1).strip()
                extracted["preset_name"] = params["preset_name"]
        stage_id = f"stage_{index + 1:02d}_substance_painter_{operation.replace('.', '_')}"
        for parameter, value in params.items():
            parameter_provenance.append({
                "stage": stage_id,
                "parameter": parameter,
                "value": value,
                "source": "user_prompt" if parameter in extracted else "registered_function_default",
            })
        for parameter in contract["required"]:
            if params.get(parameter) in (None, "", [], {}):
                required_inputs.append({
                    "stage": stage_id,
                    "host": "substance_painter",
                    "argument": parameter,
                    "question": f"What should `{parameter}` use for {contract['label']}?",
                })
        stages.append({
            "id": stage_id,
            "host": "substance_painter",
            "operation": operation,
            "callable": contract["callable"],
            "params": params,
            "implementation_state": contract["implementation_state"],
            "execution_mode": contract["metadata"].get("execution_mode", "host_native"),
        })
    graph = ActionGraph(
        goal=prompt,
        intent="pipeline_capability_acquisition",
        confidence=0.95,
        diagnostics=[
            "Painter smart-material application is a user-delegated host-UI step, not an executable pipeline callable."
        ],
    ).to_dict()
    gap = {
        "kind": "operation_evidence_gap",
        "host": "substance_painter",
        "operation": "material.apply",
        "implementation_state": "user_delegated",
        "execution_blocked": True,
        "reason": (
            "Apply the smart material in Substance Painter and provide an explicit "
            "delegation receipt before downstream texture export can run."
        ),
    }
    graph.update({
        "framework": "dynamic_typed_pipeline_v1",
        "success": False,
        "execution_ready": False,
        "hosts": ["substance_painter"],
        "selected_contracts": contracts,
        "requested_operations": requested,
        "stages": stages,
        "required_inputs": required_inputs,
        "parameter_provenance": parameter_provenance,
        "gaps": [gap],
        "capability_gaps": [gap],
    })
    graph["validation"] = validate_action_graph(graph)
    return graph


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
    host_prompt = str(prompt or "")
    if host == "unreal":
        # A Maya retarget before "then import into Unreal" is not a request
        # to retarget again inside Unreal. Match post-import verbs only in the
        # final Unreal clause, while retaining genuine Unreal-side edits.
        mentions = list(re.finditer(r"\bunreal(?:\s+engine)?\b", host_prompt, re.IGNORECASE))
        if mentions:
            host_prompt = host_prompt[mentions[-1].start():]
    # File basenames and Unreal package folders such as /Game/Animations are
    # not requests to run a post-import operation.
    without_files = re.sub(
        r"(?<!\w)[A-Za-z]:[\\/][^,;\n]*?\.(?:fbx|ma|mb|uasset|usd|abc)\b",
        " ", host_prompt, flags=re.IGNORECASE,
    )
    without_files = re.sub(
        r"(?<!\w)/Game(?:/[A-Za-z0-9_]+)+", " ", without_files,
        flags=re.IGNORECASE,
    )
    lower = re.sub(r"[^a-z0-9]+", " ", without_files.lower())
    prompt_tokens = {token for token in lower.split() if len(token) > 3}
    rows = []
    for contract in operation_contracts(host=host, role="post_import", subject=subject):
        if contract.operation == "unreal.create_blendspace" and not re.search(
            r"\bblend\s*space\b|\bbs_[a-z0-9_]+\b", lower
        ):
            continue
        if contract.operation == "animation.report_pipeline_assets" and not re.search(
            r"\breport\b.{0,60}\b(?:final\s+)?(?:animation\s+)?pipeline\s+assets?\b|"
            r"\b(?:final\s+)?(?:animation\s+)?pipeline\s+assets?\b.{0,60}\breport\b",
            lower,
        ):
            # A generic "report registry readback" should use the registry
            # validator, not demand an animation_paths artifact from a final
            # animation report that the user never requested.
            continue
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
        r"\b(?:only\s+)?(?:the\s+)?selected\s+"
        r"(?:(?:prop|static|source|scene|game|high|low|asset)\s+){0,2}"
        r"(?:objects?|items?|mesh(?:es)?|models?|props?|assets?)\b|"
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
    for candidate in ("export_path", "output_path", "output_fbx", "filepath"):
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


def _named_static_meshes(prompt: str) -> list[str]:
    """Parse an exact 2–5 item named-mesh list without guessing asset identities."""
    match = re.search(
        r"\b(two|three|four|five|[2-5])\s+"
        r"(?:(?:distinct|different|separate)\s+)?"
        r"(?:static\s+)?meshes?\s+named\s+",
        prompt,
        re.IGNORECASE,
    )
    if not match:
        return []
    count = {"two": 2, "three": 3, "four": 4, "five": 5}.get(
        match.group(1).lower(), int(match.group(1)) if match.group(1).isdigit() else 0
    )
    tail = prompt[match.end():]
    names: list[str] = []
    cursor = 0
    for index in range(count):
        item = re.match(r"\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", tail[cursor:])
        if not item:
            return []
        names.append(item.group(1))
        cursor += item.end()
        if index < count - 1:
            separator = re.match(r"\s*(?:,\s*(?:and\s+)?|and\s+)", tail[cursor:], re.IGNORECASE)
            if not separator:
                return []
            cursor += separator.end()
    if len({name.lower() for name in names}) != count:
        return []
    extra = re.match(r"\s*,\s*(?:and\s+)?([A-Za-z_][A-Za-z0-9_]*)", tail[cursor:], re.IGNORECASE)
    if extra and extra.group(1).lower() not in {
        "from", "as", "to", "then", "export", "import", "save", "validate",
        "apply", "clean", "generate", "create", "with", "into",
    }:
        return []
    return names


def _requested_motionbuilder_steps(prompt: str) -> list[str]:
    lower = str(prompt or "").lower()
    requested = []
    if re.search(r"\b(?:characteri[sz]e|create\s+(?:a\s+)?character)\b", lower):
        requested.append("character.create_character")
    if re.search(r"\bplot\b.{0,48}\b(?:animation|skeleton|control\s+rig|rig)\b", lower):
        requested.append("character.plot_animation")
    return requested


def _explicit_engine_project_root(prompt: str) -> str:
    """Read an explicitly named engine project without confusing it with an FBX path."""

    match = re.search(
        r"\b(?:tech\s+connector(?:\s+engine)?|tc\s+engine|engine)\s+project"
        r"(?:\s+(?:root|folder|directory))?\s*(?:at|in|under|:)\s*"
        r"(?:\"(?P<double>[A-Za-z]:[\\/][^\"\n]+)\"|"
        r"'(?P<single>[A-Za-z]:[\\/][^'\n]+)'|"
        r"(?P<plain>[A-Za-z]:[\\/][^\s,;]+))",
        str(prompt or ""),
        re.IGNORECASE,
    )
    if match is None:
        return ""
    path = match.group("double") or match.group("single") or match.group("plain") or ""
    if match.group("plain"):
        path = path.rstrip(".,;:)]}")
    return path.replace("\\", "/")


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
    frame_ranges = re.findall(
        r"\b(?:frames?|frame\s+range)\s*(\d+)\s*(?:-|to|through)\s*(\d+)\b",
        lower,
    )
    if len(frame_ranges) == 1 and {"start_frame", "end_frame"}.issubset(params):
        start, end = (int(value) for value in frame_ranges[0])
        if start <= end:
            params["start_frame"] = start
            params["end_frame"] = end
    if contract.operation == "blender.clean_animation":
        if len(frame_ranges) == 1:
            params["frame_range"] = [int(value) for value in frame_ranges[0]]
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
        if re.search(r"\bbevel(?:s|ed|ing)?\b", lower):
            width_match = re.search(
                r"\bbevel(?:s|ed|ing)?\b.{0,40}?\b(?:by|width|of|at)\s+"
                r"(\d+(?:\.\d+)?)\b",
                lower,
            )
            if not width_match:
                width_match = re.search(
                    r"\bbevel(?:s|ed|ing)?\b.{0,32}?\b(\d+(?:\.\d+)?)\b"
                    r"(?!\s+segments?\b)",
                    lower,
                )
            params["bevel_width"] = (
                float(width_match.group(1)) if width_match else 0.02
            )
            segments_match = re.search(r"\b(\d+)\s+segments?\b", lower)
            if segments_match:
                params["bevel_segments"] = int(segments_match.group(1))


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
    allow_single_host: bool = False,
    use_default_settings: bool = True,
    custom_settings: dict[str, Any] | None = None,
    requirement_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hosts = extract_ordered_hosts(prompt)
    format_name = infer_pipeline_format(prompt)
    subject = infer_pipeline_subject(prompt)
    if len(hosts) < 2 and not (allow_single_host and len(hosts) == 1):
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
    multi_asset_request = re.search(
        r"\b(?:two|three|four|five|[2-9]|multiple|several)\s+"
        r"(?:(?:distinct|different|separate)\s+)?"
        r"(?:(?:animation|mocap|static|skeletal|rigged|character)\s+)?"
        r"(?:takes?|clips?|animations?|meshes?|assets?|props?|textures?|materials?)\b",
        prompt,
        flags=re.IGNORECASE,
    ) or re.search(
        # A character and a separately named motion clip are two artifacts
        # even when the user never says "two". A single animated character
        # remains eligible for the established one-lane pipeline.
        r"\b(?:rigged|skeletal|skinned)\s+(?:\w+\s+){0,2}"
        r"(?:hero|character|avatar|mesh)\s+and\s+(?:a|an|the)\s+"
        r"(?:(?:walk|run|idle|jump|mocap|animation)\s+)?"
        r"(?:cycle|clip|take|animation)\b",
        prompt,
        flags=re.IGNORECASE,
    ) or re.search(
        # "Walk and Run takes" names two independent clips without a count.
        r"\b[A-Z][A-Za-z0-9_]*\s+and\s+[A-Z][A-Za-z0-9_]*\s+"
        r"(?:takes?|clips?|animations?|actions?)\b",
        prompt,
    )
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
    maya_control_transfer = bool(
        hosts[0] == "maya"
        and subject == "animation"
        and re.search(r"\b(?:transfer|retarget|bake)\b", prompt, re.IGNORECASE)
        and re.search(r"\b(?:control\s*rig|animator\s*controls?)\b", prompt, re.IGNORECASE)
        and re.search(r"\b(?:animation|mocap)\s+fbx\b", prompt, re.IGNORECASE)
    )
    maya_transfer_params = (
        build_dcc_operation_params("maya", "animation.fbx_to_engine", prompt)
        if maya_control_transfer else {}
    )
    if maya_control_transfer:
        transfer_inputs = [
            str(maya_transfer_params.get(key) or "")
            for key in ("animation_fbx", "rig_scene", "target_hik_fbx", "source_hik_fbx")
        ]
        transfer_outputs = [
            str(maya_transfer_params.get(key) or "")
            for key in ("output_scene", "output_fbx")
        ]
        resolved_inputs = {str(Path(value).expanduser().resolve()).lower()
                           for value in transfer_inputs if value}
        resolved_outputs = [str(Path(value).expanduser().resolve()).lower()
                            for value in transfer_outputs if value]
        if (any(value in resolved_inputs for value in resolved_outputs)
                or len(resolved_outputs) != len(set(resolved_outputs))):
            gaps.append({
                "kind": "output_aliases_input",
                "execution_blocked": True,
                "message": "Maya transfer outputs must not overwrite source FBX, rig, HIK, or each other.",
            })
    process_requested = bool(
        re.search(
            r"\b(clean|process|bake|retarget|optimi[sz]e|rename|transforms?|"
            r"collision|collider|lods?|material|bevel(?:s|ed|ing)?)\b",
            str(prompt or "").lower(),
        )
    )
    if re.search(
        r"\b(?:adjust|edit|modify|change|remove|correct|fix)\s+"
        r"(?:the\s+)?root[- ]motion\b",
        str(prompt or ""),
        flags=re.IGNORECASE,
    ):
        # Registered animation cleanup preserves root-motion metadata; it
        # does not implement an arbitrary root-motion edit. Fail closed.
        gaps.append({
            "kind": "missing_requested_operation",
            "host": hosts[1] if len(hosts) > 1 else hosts[0],
            "role": "process",
            "subject": subject,
            "execution_blocked": True,
            "message": "No verified operation edits root motion; this step cannot be omitted.",
        })
    if re.search(
        r"\bBlender\b.{0,80}\b(?:change|paint|edit|adjust|modify|set)\b"
        r".{0,24}\b(?:skin\s+)?weights?\b",
        str(prompt or ""),
        flags=re.IGNORECASE,
    ):
        gaps.append({
            "kind": "missing_requested_operation",
            "host": "blender",
            "role": "process",
            "subject": subject,
            "execution_blocked": True,
            "message": "No verified Blender skin-weight edit is selected; this step cannot be omitted.",
        })
    if "blender" in hosts:
        # The registered transfer processor covers names, transforms, bevel,
        # LODs, material slots, and collision—not arbitrary mesh editing. Never
        # compile an export chain that silently drops one of these edits.
        unverified_blender_edits = (
            ("UV generation", r"\b(?:generate|create|unwrap|edit|adjust)\b"
             r".{0,24}\b(?:UVs?|UV\s+maps?|UV\s+unwrap)\b"),
            ("decimation", r"\bdecimat(?:e|es|ed|ion)\b"),
            ("blendshape editing", r"\b(?:add|create|edit|adjust|modify)\b"
             r".{0,24}\b(?:blend\s*shapes?|shape\s*keys?)\b"),
        )
        for edit_name, pattern in unverified_blender_edits:
            if re.search(pattern, str(prompt or ""), flags=re.IGNORECASE):
                gaps.append({
                    "kind": "missing_requested_operation",
                    "host": "blender",
                    "role": "process",
                    "subject": subject,
                    "execution_blocked": True,
                    "message": f"No verified Blender {edit_name} operation is selected; this step cannot be omitted.",
                })
        if re.search(
            r"\bbevel(?:s|ed|ing)?\b.{0,30}\b(?:selected|specific|marked)\s+edges?\b",
            str(prompt or ""), flags=re.IGNORECASE,
        ):
            gaps.append({
                "kind": "missing_requested_operation",
                "host": "blender", "role": "process", "subject": subject,
                "execution_blocked": True,
                "message": "The transfer bevel acts on angle-limited edges, not an arbitrary selected edge set.",
            })
        if subject == "skeletal_mesh" and re.search(
            r"\bbevel(?:s|ed|ing)?\b", str(prompt or ""), flags=re.IGNORECASE,
        ):
            gaps.append({
                "kind": "missing_requested_operation",
                "host": "blender", "role": "process", "subject": subject,
                "execution_blocked": True,
                "message": "The transfer bevel is qualified for static meshes only; skinned-mesh export is unverified.",
            })
    if process_requested and not maya_control_transfer:
        source_processor = _select_contract(
            hosts[0], "process", format_name, subject, prompt
        )
        if source_processor:
            selected.append(source_processor)
    exporter = (
        registered_operation_contract("maya", "animation.fbx_to_engine")
        if maya_control_transfer and format_name == "fbx"
        else registered_operation_contract("maya", "animation.export")
        if hosts[0] == "maya" and subject == "animation"
        else _select_contract(hosts[0], "export", format_name, subject, prompt)
    )
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

    # A first-host import is a real stage, not an implicit scene state. This
    # matters for prompts that start with an existing FBX in MotionBuilder.
    first_host_import = bool(
        hosts[0] == "motionbuilder"
        and re.search(r"\bimport\b.{0,140}\.fbx\b", prompt, re.IGNORECASE)
    )
    if first_host_import:
        importer = _select_contract(hosts[0], "import", format_name, subject, prompt)
        if importer:
            selected.insert(0, importer)
        else:
            gaps.append({
                "kind": "missing_requested_operation",
                "host": hosts[0],
                "role": "import",
                "message": "The requested MotionBuilder FBX import is not registered.",
            })

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

    if (
        format_name == "fbx"
        and subject in {"skeletal_mesh", "animation"}
        and any(
            contract.host == "tech_connector"
            and contract.operation == "asset.import_interchange"
            for contract in selected
        )
    ):
        gaps.append({
            "kind": "unsupported_character_interchange",
            "host": "tech_connector",
            "format": "fbx",
            "subject": subject,
            "execution_blocked": True,
            "message": (
                "The Tech Connector engine FBX asset import currently registers FBX "
                "as a static mesh; it does not create a cooked skeletal mesh, "
                "skeleton, skin binding, or animation asset. This rigged transfer "
                "cannot be marked ready until a verified character importer is wired."
            ),
        })

    if "motionbuilder" in hosts:
        motionbuilder_steps = _requested_motionbuilder_steps(prompt)
        if motionbuilder_steps:
            insertion = next(
                (index for index, item in enumerate(selected)
                 if item.host == "motionbuilder" and item.role == "export"),
                len(selected),
            )
            for operation in motionbuilder_steps:
                contract = registered_operation_contract("motionbuilder", operation)
                if contract is None or not contract.executable:
                    gaps.append({
                        "kind": "missing_requested_operation",
                        "host": "motionbuilder",
                        "operation": operation,
                        "message": f"Requested MotionBuilder step {operation} is unavailable.",
                    })
                elif not any(item.key == contract.key for item in selected):
                    selected.insert(insertion, contract)
                    insertion += 1

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
    # Multi-asset lanes require explicit source identity and a fully verified
    # operation sequence. Each named mesh gets its own typed handoff chain;
    # unrecognized asset types and intermediate edits still fail closed.
    named_meshes = _named_static_meshes(prompt)
    requested_transfer_paths = _explicit_transfer_paths(prompt, format_name)
    lane_explicit_paths: dict[str, str] = {}
    if (named_meshes and tuple(hosts) == ("blender", "unreal")
            and len(requested_transfer_paths) == len(named_meshes)):
        by_stem = {Path(path).stem.lower(): path for path in requested_transfer_paths}
        if len(by_stem) == len(named_meshes) and set(by_stem) == {name.lower() for name in named_meshes}:
            lane_explicit_paths = {name: by_stem[name.lower()] for name in named_meshes}
    lane_names: list[str] = []
    supported_lane_roles = {
        ("blender", "unreal"): ["export", "import", "validate"],
        ("maya", "blender", "unreal"): [
            "export", "import", "process", "export", "import", "validate"
        ],
    }
    if (
        named_meshes
        and multi_asset_request
        and tuple(hosts) in supported_lane_roles
        and format_name == "fbx"
        and subject == "static_mesh"
        and process_requested == (hosts == ["maya", "blender", "unreal"])
        and (len(named_meshes) == 2 or tuple(hosts) == ("blender", "unreal"))
        and (not requested_transfer_paths or bool(lane_explicit_paths))
        and [item.role for item in selected] == supported_lane_roles[tuple(hosts)]
    ):
        lane_names = list(named_meshes)
    if multi_asset_request and not lane_names and re.search(
        r"\b(?:export|transfer|import)\b", prompt, re.IGNORECASE
    ):
        gaps.append({
            "kind": "unsupported_multi_asset_transfer",
            "requested_assets": multi_asset_request.group(0),
            "execution_blocked": True,
            "message": (
                "No verified independent artifact lanes match every requested "
                "asset and edit. Supported narrow paths require two to five distinct "
                "named static meshes for Blender to Unreal, or two named Maya meshes "
                "through a Blender edit and re-export to Unreal."
            ),
        })
    if (
        process_requested
        and not maya_control_transfer
        and not any(
            contract.role in {"process", "operate", "post_import"}
            for contract in selected
        )
        and re.search(
            r"\b(clean|process|retarget|optimi[sz]e|rename|lods?|"
            r"collision|collider)\b|\b(?:apply|freeze)\s+transforms?\b|"
            r"\bmaterial\s+slots?\b",
            str(prompt or "").lower(),
        )
    ):
        gaps.append({
            "kind": "missing_requested_operation",
            "host": hosts[0],
            "role": "process",
            "subject": subject,
            "message": (
                "The prompt requests processing, but no selected stage can perform "
                "it. Export will not silently omit that step."
            ),
        })
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
            "gaps": gaps,
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
    lane_contracts = list(selected)
    if lane_names:
        selected = lane_contracts * len(lane_names)
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
    explicit_paths = [] if lane_explicit_paths else list(requested_transfer_paths)
    if maya_control_transfer:
        source_fbx = str(maya_transfer_params.get("animation_fbx") or "").replace("\\", "/")
        explicit_paths = [path for path in explicit_paths if path != source_fbx]
    first_import_source = explicit_paths.pop(0) if first_host_import and explicit_paths else ""
    explicit_engine_project_root = _explicit_engine_project_root(prompt)
    export_index = 0
    unreal_destination, unreal_skeleton = _unreal_path_params(prompt)
    settings = dict(custom_settings or {})
    custom_unreal_destination = str(settings.get("unreal_destination_path") or "").strip()
    parameter_provenance: list[dict[str, Any]] = []
    literal_artifacts = {
        "skeleton_path": unreal_skeleton,
    }

    for index, contract in enumerate(selected, start=1):
        lane_name = lane_names[(index - 1) // len(lane_contracts)] if lane_names else ""
        if lane_names and (index - 1) % len(lane_contracts) == 0:
            available.clear()
            # Independent named assets must not inherit the previous lane's
            # dependency chain. Otherwise one failed import skips every later
            # asset and serializes work that could be handled independently.
            previous_action_id = ""
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
        if contract.host == "maya" and contract.operation == "animation.fbx_to_engine":
            params.update(maya_transfer_params)
        if contract.host == "maya" and contract.operation == "animation.export" and subject in {"asset", "static_mesh"}:
            # The same FBX callable exports meshes, but baking 120 animation
            # frames for a static handoff adds avoidable work and latency.
            params["bake_animation"] = False
        if contract.host == "blender" and subject in {"asset", "static_mesh"}:
            if contract.operation == "io.export_fbx":
                params["bake_animation"] = False
            elif contract.operation == "blender.export_fbx":
                params["settings"] = {**params.get("settings", {}), "bake_animation": False}
        _apply_prompt_parameters(contract, params, prompt)
        if contract.host == "motionbuilder" and contract.operation in {
            "character.create_character", "character.plot_animation"
        }:
            name_match = re.search(
                r"\b(?:characteri[sz]e\s+(?:the\s+)?rig\s+as|"
                r"character\s+(?:named|called)|plot\s+(?:the\s+)?animation\s+for)\s+"
                r"['\"]?([A-Za-z_][A-Za-z0-9_]*)",
                prompt,
                re.IGNORECASE,
            )
            if name_match:
                params["character_name"] = name_match.group(1)
            if contract.operation == "character.plot_animation":
                fps_match = re.search(r"\b(?:at\s+)?(\d+(?:\.\d+)?)\s*fps\b", prompt, re.IGNORECASE)
                if fps_match:
                    params["fps"] = float(fps_match.group(1))
                if re.search(r"\bplot\b.{0,48}\b(?:to|onto)\s+(?:the\s+)?skeleton\b", prompt, re.IGNORECASE):
                    params["plot_to_rig"] = False
        if first_import_source and contract.host == hosts[0] and contract.role == "import":
            params["filepath"] = first_import_source
            parameter_provenance.append({
                "stage": action_id,
                "parameter": "filepath",
                "value": first_import_source,
                "source": "user_prompt",
                "resolution": "Import the source FBX named before the export destination.",
            })
        if (
            contract.operation == "pipeline.process_meshes_for_transfer"
            and re.search(r"\blods?\b", prompt, re.IGNORECASE)
            and not re.search(r"\blod\s*\d+\b", prompt, re.IGNORECASE)
            and setting_for("lod_count") in (None, "", 0, "0", [], {})
        ):
            required_inputs.append({
                "stage": action_id,
                "host": contract.host,
                "argument": "lod_count",
                "question": "How many LOD levels should Blender generate?",
            })
            parameter_provenance.append({
                "stage": action_id,
                "parameter": "lod_count",
                "value": params.get("lod_count"),
                "source": "required_user_input",
                "resolution": "LOD generation was requested without a level or count; the registered zero default would skip it.",
            })
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
                and not params.get(_input_parameter(contract, consumed, contract.role))
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
        if lane_name and contract.host == hosts[0] and contract.role == "export":
            params[context_parameter] = {
                "$pipeline_context": "dcc_export_scope_v1",
                "host": hosts[0],
                "scope": "named_object",
                "subject": "static_mesh",
                "name": lane_name,
                "label": f"Named mesh {lane_name}",
            }
            parameter_provenance.append({
                "stage": action_id,
                "parameter": context_parameter,
                "value": params[context_parameter],
                "source": "user_prompt_named_asset",
                "resolution": f"Resolve exactly this named mesh in the live {hosts[0]} scene.",
            })

        if contract.role == "export":
            output_parameter = _output_parameter(contract)
            if output_parameter:
                if contract.operation == "animation.fbx_to_engine" and params.get(output_parameter):
                    parameter_provenance.append({
                        "stage": action_id,
                        "parameter": output_parameter,
                        "value": params[output_parameter],
                        "source": "user_prompt_labeled_output",
                        "resolution": "The engine FBX output is explicitly labeled in the prompt.",
                    })
                elif lane_name and lane_explicit_paths:
                    params[output_parameter] = lane_explicit_paths[lane_name]
                    parameter_provenance.append({
                        "stage": action_id,
                        "parameter": output_parameter,
                        "value": params[output_parameter],
                        "source": "user_prompt_named_asset_path",
                        "resolution": f"Explicit FBX basename matches named mesh {lane_name}.",
                    })
                elif export_index < len(explicit_paths):
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
                    output_stem = (
                        f"{lane_name}_{contract.host}" if lane_name and len(hosts) > 2
                        else lane_name or action_id
                    )
                    params[output_parameter] = str(
                        Path("${pipeline_workspace}") / f"{output_stem}{suffix}"
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
            if ("asset_transfer_adapter.import_fbx_verified" in contract.callable
                    and subject in {"asset", "static_mesh"}):
                params["assemble_lods"] = bool(
                    re.search(r"\blod\s*[1-9][0-9]*\b", prompt, re.IGNORECASE)
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
            configured_root = str(
                explicit_engine_project_root or setting_for("project_root") or project_root or ""
            ).strip()
            params["project_root"] = configured_root
            if explicit_engine_project_root:
                parameter_provenance.append({
                    "stage": action_id,
                    "parameter": "project_root",
                    "value": configured_root,
                    "source": "user_prompt",
                    "resolution": "Import into the engine project explicitly named in the prompt.",
                })
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
                "asset_lane": lane_name,
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
                "asset_lane": lane_name,
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
            "asset_lanes": [
                {"name": name, "subject": "static_mesh", "source_host": hosts[0]}
                for name in lane_names
            ],
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

