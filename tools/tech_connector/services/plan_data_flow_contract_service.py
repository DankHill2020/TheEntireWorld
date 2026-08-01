"""Materialize callable surfaces and data-flow obligations for edit plans."""

from __future__ import annotations

import ast
from collections import defaultdict
import re
from typing import Any, Iterable, Mapping


_ACTION_PREFIXES = (
    "build", "connect", "convert", "copy", "create", "export", "find",
    "generate", "get", "import", "load", "query", "read", "save", "select",
    "set", "sync", "update", "validate", "write",
)
_NON_DATA_OPERATIONS = {
    "available", "check", "confirm", "exists", "is", "validate",
}


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _symbol_parts(qualified_name: str) -> tuple[str, str]:
    terminal = str(qualified_name or "").rsplit(".", 1)[-1]
    pieces = [
        value.casefold()
        for value in re.split(
            r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])",
            terminal,
        )
        if value
    ]
    action = next(
        (
            prefix
            for prefix in _ACTION_PREFIXES
            if pieces and pieces[0].startswith(prefix)
        ),
        pieces[0] if pieces else "",
    )
    artifact = "_".join(
        value
        for value in pieces[1:]
        if value not in {"asset", "data", "file", "item", "result", "value"}
    )
    if not artifact and len(pieces) > 1:
        artifact = pieces[-1]
    return action, artifact


def _parse_signature(signature: str) -> dict[str, Any]:
    source = str(signature or "").strip()
    open_index = source.find("(")
    if open_index < 0:
        return {
            "parameters": [],
            "required_parameters": [],
            "return_annotation": "",
            "parse_status": "unparsed",
        }
    depth = 0
    close_index = -1
    quote = ""
    escaped = False
    for index, character in enumerate(source[open_index:], open_index):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break
    if close_index < 0:
        return {
            "parameters": [],
            "required_parameters": [],
            "return_annotation": "",
            "parse_status": "unparsed",
        }
    parameter_source = source[open_index:close_index + 1]
    tail = source[close_index + 1:].strip()
    return_source = (
        tail[2:].strip() if tail.startswith("->") else ""
    )
    try:
        tree = ast.parse(
            f"def _surface{parameter_source}"
            + (f" -> {return_source}" if return_source else "")
            + ":\n    pass\n"
        )
        function = tree.body[0]
    except (SyntaxError, ValueError, TypeError):
        return {
            "parameters": [],
            "required_parameters": [],
            "return_annotation": return_source,
            "parse_status": "unparsed",
        }

    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    default_offset = len(positional) - len(arguments.defaults)
    parameters: list[dict[str, Any]] = []
    for index, argument in enumerate(positional):
        default_node = (
            arguments.defaults[index - default_offset]
            if index >= default_offset
            else None
        )
        parameters.append({
            "name": argument.arg,
            "kind": "positional",
            "annotation": (
                ast.unparse(argument.annotation)
                if argument.annotation is not None
                else ""
            ),
            "required": (
                argument.arg not in {"self", "cls"}
                and default_node is None
            ),
            "default": (
                ast.unparse(default_node)
                if default_node is not None
                else ""
            ),
        })
    for argument, default_node in zip(
        arguments.kwonlyargs,
        arguments.kw_defaults,
    ):
        parameters.append({
            "name": argument.arg,
            "kind": "keyword_only",
            "annotation": (
                ast.unparse(argument.annotation)
                if argument.annotation is not None
                else ""
            ),
            "required": default_node is None,
            "default": (
                ast.unparse(default_node)
                if default_node is not None
                else ""
            ),
        })
    if arguments.vararg is not None:
        parameters.append({
            "name": arguments.vararg.arg,
            "kind": "var_positional",
            "annotation": (
                ast.unparse(arguments.vararg.annotation)
                if arguments.vararg.annotation is not None
                else ""
            ),
            "required": False,
            "default": "",
        })
    if arguments.kwarg is not None:
        parameters.append({
            "name": arguments.kwarg.arg,
            "kind": "var_keyword",
            "annotation": (
                ast.unparse(arguments.kwarg.annotation)
                if arguments.kwarg.annotation is not None
                else ""
            ),
            "required": False,
            "default": "",
        })
    return {
        "parameters": parameters,
        "required_parameters": [
            item["name"] for item in parameters if item["required"]
        ],
        "return_annotation": (
            ast.unparse(function.returns)
            if function.returns is not None
            else return_source
        ),
        "parse_status": "parsed",
    }


def _requirement_rows(plan: Mapping[str, Any]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for key in ("requirements", "requirement_ledger"):
        for raw_item in plan.get(key) or []:
            if not isinstance(raw_item, Mapping):
                continue
            requirement_id = str(
                raw_item.get("id") or raw_item.get("requirement_id") or ""
            )
            if requirement_id:
                rows[requirement_id] = str(raw_item.get("text") or "")
    for chunk in plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        for raw_item in chunk.get("requirements") or []:
            if not isinstance(raw_item, Mapping):
                continue
            requirement_id = str(
                raw_item.get("id") or raw_item.get("requirement_id") or ""
            )
            if requirement_id:
                rows[requirement_id] = str(raw_item.get("text") or "")
    return rows


def materialize_plan_data_flow_contracts(
    implementation_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Build immutable callable surfaces and explicit binding obligations.

    :param implementation_plan: Enriched project-edit implementation plan.
    :return: Callable surfaces, inferred flow candidates, and validation status.
    """

    requirements = _requirement_rows(implementation_plan)
    surfaces: list[dict[str, Any]] = []
    hard_errors: list[str] = []
    evidence_ids: set[str] = set()
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        owner = str(chunk.get("owner") or "<module>")
        path = str(chunk.get("path") or "")
        for raw_record in chunk.get("evidence") or []:
            if not isinstance(raw_record, Mapping):
                continue
            if not raw_record.get("selected_for_generation"):
                continue
            record = dict(raw_record)
            qualified_name = str(record.get("qualified_name") or "")
            signature = str(record.get("signature") or "")
            evidence_id = str(
                record.get("evidence_id")
                or record.get("id")
                or "|".join((
                    qualified_name,
                    signature,
                    str(record.get("path") or ""),
                ))
            )
            if evidence_id in evidence_ids:
                continue
            evidence_ids.add(evidence_id)
            access_kind = str(
                record.get("access_kind")
                or record.get("kind")
                or "callable"
            ).casefold()
            callable_surface = bool(
                access_kind
                not in {"property", "attribute", "constant", "field"}
                and (
                    bool(signature)
                    or access_kind
                    in {
                        "callable", "capability", "class", "function",
                        "method", "operation",
                    }
                )
            )
            parsed = (
                _parse_signature(signature)
                if callable_surface and signature
                else {
                "parameters": [],
                "required_parameters": [],
                "return_annotation": str(record.get("return_type") or ""),
                "parse_status": (
                    "missing_signature"
                    if callable_surface
                    else "not_callable"
                ),
            })
            action, artifact = _symbol_parts(qualified_name)
            requirement_ids = _ordered_unique(
                str(value)
                for value in record.get("requirement_ids") or []
            )
            surface = {
                "evidence_id": evidence_id,
                "owner": owner,
                "path": path,
                "qualified_name": qualified_name,
                "import_statement": str(
                    record.get("import_statement") or ""
                ),
                "signature": signature,
                "access_kind": access_kind,
                "callable": callable_surface,
                "authoritative": bool(
                    record.get("authoritative_signature")
                ),
                "parameters": parsed["parameters"],
                "required_parameters": parsed["required_parameters"],
                "return_annotation": (
                    parsed["return_annotation"]
                    or str(record.get("return_type") or "")
                ),
                "parse_status": parsed["parse_status"],
                "operation": action,
                "artifact": artifact,
                "requirement_ids": requirement_ids,
                "requirement_text": [
                    requirements[value]
                    for value in requirement_ids
                    if value in requirements
                ],
                "source_path": str(record.get("path") or ""),
                "provider": str(record.get("provider") or ""),
            }
            surfaces.append(surface)
            if callable_surface and not signature:
                hard_errors.append(
                    f"{path}:{owner} selected callable {qualified_name} "
                    "without a signature."
                )
            if callable_surface and parsed["parse_status"] != "parsed":
                hard_errors.append(
                    f"{path}:{owner} selected callable {qualified_name} has "
                    f"an unparseable signature: {signature}"
                )
        for task in chunk.get("method_tasks") or []:
            if not isinstance(task, Mapping):
                continue
            method_name = str(task.get("name") or "")
            signature = str(task.get("signature") or "")
            if not method_name or method_name.startswith("_") or not signature:
                continue
            evidence_id = "|".join((
                "approved_plan_declaration",
                path,
                owner,
                method_name,
                signature,
            ))
            if evidence_id in evidence_ids:
                continue
            evidence_ids.add(evidence_id)
            parsed = _parse_signature(signature)
            action, artifact = _symbol_parts(method_name)
            requirement_ids = _ordered_unique(
                str(value)
                for value in task.get("requirement_ids") or []
            )
            surfaces.append({
                "evidence_id": evidence_id,
                "owner": owner,
                "path": path,
                "qualified_name": f"{owner}.{method_name}",
                "import_statement": "",
                "signature": signature,
                "access_kind": "method",
                "callable": True,
                "authoritative": True,
                "parameters": parsed["parameters"],
                "required_parameters": parsed["required_parameters"],
                "return_annotation": parsed["return_annotation"],
                "parse_status": parsed["parse_status"],
                "operation": action,
                "artifact": artifact,
                "requirement_ids": requirement_ids,
                "requirement_text": [
                    requirements[value]
                    for value in requirement_ids
                    if value in requirements
                ],
                "source_path": path,
                "provider": "approved_plan_declaration",
            })

    flow_candidates: list[dict[str, Any]] = []
    binding_obligations: list[dict[str, Any]] = []
    surfaces_by_owner: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for surface in surfaces:
        surfaces_by_owner[(surface["path"], surface["owner"])].append(surface)

    chunks_by_id = {
        str(chunk.get("chunk_id") or ""): chunk
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and str(chunk.get("chunk_id") or "")
    }
    for consumer_chunk in implementation_plan.get("chunks") or []:
        if not isinstance(consumer_chunk, Mapping):
            continue
        for interface in (
            consumer_chunk.get("required_dependency_interfaces") or []
        ):
            if not isinstance(interface, Mapping):
                continue
            producer_chunk = chunks_by_id.get(
                str(interface.get("producer_chunk") or ""),
                {},
            )
            producer_owner = str(producer_chunk.get("owner") or "")
            signature = str(interface.get("signature") or "")
            method_match = re.match(
                r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                signature,
            )
            method_name = method_match.group(1) if method_match else ""
            parsed = _parse_signature(signature)
            requirement_ids = _ordered_unique(
                str(value)
                for task in producer_chunk.get("method_tasks") or []
                if isinstance(task, Mapping)
                and str(task.get("name") or "") == method_name
                for value in task.get("requirement_ids") or []
            )
            for parameter in parsed["required_parameters"]:
                binding_obligations.append({
                    "path": str(consumer_chunk.get("path") or ""),
                    "owner": str(consumer_chunk.get("owner") or ""),
                    "consumer": f"{producer_owner}.{method_name}",
                    "parameter": parameter,
                    "requirement_ids": requirement_ids,
                    "rule": (
                        "Bind this approved cross-file dependency parameter "
                        "from a declared consumer control, event-loop-safe "
                        "signal/callback, or verified prior result."
                    ),
                    "validation_status": "generation_must_prove",
                })

    for (path, owner), owner_surfaces in surfaces_by_owner.items():
        for consumer in owner_surfaces:
            required_parameters = list(consumer["required_parameters"])
            for parameter in required_parameters:
                binding_obligations.append({
                    "path": path,
                    "owner": owner,
                    "consumer": consumer["qualified_name"],
                    "parameter": parameter,
                    "requirement_ids": consumer["requirement_ids"],
                    "rule": (
                        "Bind from an explicit owner input, verified prior "
                        "call result, or declared transformation; never invent "
                        "a constant or silently drop the parameter."
                    ),
                    "validation_status": "generation_must_prove",
                })
            for producer in owner_surfaces:
                if producer is consumer:
                    continue
                if producer["operation"] in _NON_DATA_OPERATIONS:
                    continue
                shared_requirements = sorted(set(
                    producer["requirement_ids"]
                ) & set(consumer["requirement_ids"]))
                same_artifact = bool(
                    producer["artifact"]
                    and producer["artifact"] == consumer["artifact"]
                )
                if not shared_requirements and not same_artifact:
                    continue
                flow_candidates.append({
                    "path": path,
                    "owner": owner,
                    "producer": producer["qualified_name"],
                    "producer_return": producer["return_annotation"],
                    "consumer": consumer["qualified_name"],
                    "consumer_parameters": consumer["parameters"],
                    "shared_requirement_ids": shared_requirements,
                    "artifact": (
                        producer["artifact"]
                        if same_artifact
                        else ""
                    ),
                    "status": "candidate_not_assumed",
                    "rule": (
                        "Generation must explicitly select the consumer argument "
                        "source and any required transformation. Candidate proximity "
                        "alone does not prove a data-flow edge."
                    ),
                })

    return {
        "schema": "tech_connector.plan_data_flow_contracts.v1",
        "callable_surfaces": surfaces,
        "flow_candidates": flow_candidates,
        "binding_obligations": binding_obligations,
        "hard_errors": _ordered_unique(hard_errors),
        "summary": {
            "selected_callable_count": len(surfaces),
            "flow_candidate_count": len(flow_candidates),
            "binding_obligation_count": len(binding_obligations),
            "hard_error_count": len(set(hard_errors)),
        },
    }
