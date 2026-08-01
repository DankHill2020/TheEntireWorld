"""Structured pause/resume protocol for generation-time evidence questions."""

from __future__ import annotations

import json
import contextvars
from pathlib import Path
import re
from typing import Any, Mapping


EVIDENCE_REQUEST_SCHEMA = "tech_connector.generation_evidence_request.v1"
EVIDENCE_RESUME_SCHEMA = "tech_connector.generation_evidence_resume.v1"
MAX_EVIDENCE_QUERIES = 8
_GENERATION_EVIDENCE_CONTEXT: contextvars.ContextVar[
    dict[str, Any] | None
] = contextvars.ContextVar(
    "tech_connector_generation_evidence_context",
    default=None,
)


class GenerationEvidenceResolutionRequired(RuntimeError):
    """Signal that generation must pause for evidence or acquisition."""

    def __init__(
        self,
        request: Mapping[str, Any],
        resolution: Mapping[str, Any],
    ) -> None:
        self.request = dict(request)
        self.resolution = dict(resolution)
        super().__init__(
            str(
                self.resolution.get("status")
                or "generation_evidence_resolution_required"
            )
        )


def begin_generation_evidence_context(
    *,
    project_root: str | Path,
) -> contextvars.Token:
    """Start one workflow-scoped evidence resolution context."""

    return _GENERATION_EVIDENCE_CONTEXT.set({
        "project_root": str(Path(project_root).expanduser().resolve()),
        "evidence_ids": [],
        "request_fingerprints": [],
        "events": [],
        "active": True,
    })


def end_generation_evidence_context(
    token: contextvars.Token,
) -> list[dict[str, Any]]:
    """Restore the prior context and return captured resolution events."""

    context = dict(_GENERATION_EVIDENCE_CONTEXT.get() or {})
    events = list(context.get("events") or [])
    _GENERATION_EVIDENCE_CONTEXT.reset(token)
    return events


def current_generation_evidence_context() -> dict[str, Any] | None:
    """Return the current mutable workflow context, when active."""

    context = _GENERATION_EVIDENCE_CONTEXT.get()
    return context if context and context.get("active") else None


def evidence_request_protocol() -> dict[str, Any]:
    """Return the protocol embedded in every owner generation capsule."""

    return {
        "schema": EVIDENCE_REQUEST_SCHEMA,
        "allowed_when": (
            "A concrete API, property-versus-callable, argument-shape, return-"
            "contract, import-owner, or usage uncertainty remains after reading "
            "the supplied owner evidence."
        ),
        "response_shape": {
            "status": "evidence_required",
            "owner": "<exact current owner>",
            "queries": [{
                "symbol_or_capability": "<exact unresolved surface>",
                "question": "<one answerable technical question>",
                "required_fields": [
                    "qualified_name",
                    "import_statement",
                    "signature",
                    "access_kind",
                    "return_contract",
                    "source",
                ],
            }],
        },
        "rules": [
            "Return no code in the same response as evidence_required.",
            "Ask only questions that block the current owner.",
            "Do not ask again for an evidence_id already supplied.",
            f"Use at most {MAX_EVIDENCE_QUERIES} focused queries.",
            "Resume the same owner; never regenerate an already-valid owner.",
        ],
    }


def _json_object(text: str) -> dict[str, Any]:
    source = str(text or "").strip()
    fenced = re.search(
        r"```(?:json)?\s*([\s\S]*?)\s*```",
        source,
        flags=re.IGNORECASE,
    )
    candidates = [fenced.group(1).strip()] if fenced else []
    if source.startswith("{") and source.endswith("}"):
        candidates.append(source)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def parse_generation_evidence_request(
    response: str | Mapping[str, Any],
    *,
    expected_owner: str = "",
) -> dict[str, Any]:
    """Validate an evidence request without treating it as generated code."""

    payload = (
        dict(response)
        if isinstance(response, Mapping)
        else _json_object(str(response or ""))
    )
    if str(payload.get("status") or "") != "evidence_required":
        return {"is_request": False, "ok": False, "errors": []}
    errors: list[str] = []
    owner = str(payload.get("owner") or "")
    if expected_owner and owner != expected_owner:
        errors.append(
            f"Evidence request owner {owner!r} does not match "
            f"current owner {expected_owner!r}."
        )
    raw_queries = payload.get("queries") or []
    if not isinstance(raw_queries, list) or not raw_queries:
        errors.append("Evidence request must contain at least one query.")
        raw_queries = []
    if len(raw_queries) > MAX_EVIDENCE_QUERIES:
        errors.append(
            f"Evidence request exceeds {MAX_EVIDENCE_QUERIES} queries."
        )
    queries: list[dict[str, Any]] = []
    for index, raw_query in enumerate(raw_queries[:MAX_EVIDENCE_QUERIES]):
        if not isinstance(raw_query, Mapping):
            errors.append(f"Evidence query {index + 1} is not an object.")
            continue
        symbol = str(
            raw_query.get("symbol_or_capability")
            or raw_query.get("symbol")
            or raw_query.get("capability")
            or ""
        ).strip()
        question = str(raw_query.get("question") or "").strip()
        if not symbol:
            errors.append(
                f"Evidence query {index + 1} has no symbol or capability."
            )
        if not question:
            errors.append(
                f"Evidence query {index + 1} has no focused question."
            )
        queries.append({
            "symbol_or_capability": symbol,
            "question": question,
            "required_fields": list(
                raw_query.get("required_fields") or []
            ),
        })
    return {
        "is_request": True,
        "ok": not errors,
        "schema": EVIDENCE_REQUEST_SCHEMA,
        "owner": owner,
        "queries": queries,
        "errors": errors,
    }


def resolve_generation_evidence_request(
    request: Mapping[str, Any],
    *,
    project_root: str | Path,
    prior_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a validated request and build a same-owner resume capsule."""

    parsed = parse_generation_evidence_request(request)
    if not parsed.get("ok"):
        return {
            "ok": False,
            "status": "invalid_evidence_request",
            "errors": list(parsed.get("errors") or []),
        }
    query_text = "\n".join(
        f"{item['symbol_or_capability']}: {item['question']}"
        for item in parsed["queries"]
    )
    from tech_connector.services.symbol_evidence_service import (
        build_symbol_evidence_packet,
    )
    packet = build_symbol_evidence_packet(
        query_text,
        project_root=project_root,
        generated_overlay=[],
        limit=max(16, len(parsed["queries"]) * 8),
        allow_official_research=True,
        capability_search=True,
    )
    prior_ids = set(prior_evidence_ids or [])
    authoritative = []
    for raw_record in packet.get("evidence") or []:
        record = dict(raw_record)
        if not record.get("authoritative_signature"):
            continue
        evidence_id = str(
            record.get("evidence_id")
            or record.get("id")
            or "|".join((
                str(record.get("qualified_name") or ""),
                str(record.get("signature") or ""),
                str(record.get("path") or ""),
            ))
        )
        if evidence_id in prior_ids:
            continue
        record["evidence_id"] = evidence_id
        authoritative.append(record)
    unresolved = [
        *list(packet.get("unresolved_host_api_queries") or []),
        *[
            str(item.get("source_clause") or item.get("query") or item)
            for item in packet.get("unresolved_capability_intents") or []
        ],
    ]
    acquisition_requests = list(
        packet.get("capability_acquisition_requests") or []
    )
    return {
        "ok": bool(authoritative) and not unresolved,
        "status": (
            "evidence_resolved"
            if authoritative and not unresolved
            else "capability_acquisition_required"
            if acquisition_requests
            else "evidence_unresolved"
        ),
        "schema": EVIDENCE_RESUME_SCHEMA,
        "owner": parsed["owner"],
        "queries": parsed["queries"],
        "new_evidence": authoritative,
        "unresolved": unresolved,
        "capability_acquisition_requests": acquisition_requests,
        "resume_instruction": (
            "Resume the same owner with the original capsule plus new_evidence. "
            "Preserve all previously valid source and evidence IDs."
        ),
        "evidence_snapshot_id": str(packet.get("snapshot_id") or ""),
        "provider_timings": list(packet.get("provider_timings") or []),
    }


def resolve_and_resume_generation_response(
    response: Any,
    *,
    invoke_model,
    original_prompt: Any,
) -> Any:
    """Resolve evidence requests and repeatedly resume the same model call.

    ``invoke_model`` must accept one replacement prompt and preserve every other
    provider/model option from the original call.
    """

    context = current_generation_evidence_context()
    if context is None:
        return response
    current_response = response
    current_prompt = original_prompt
    while True:
        parsed = parse_generation_evidence_request(current_response)
        if not parsed.get("is_request"):
            return current_response
        if not parsed.get("ok"):
            resolution = {
                "ok": False,
                "status": "invalid_evidence_request",
                "errors": list(parsed.get("errors") or []),
            }
            context["events"].append({
                "request": parsed,
                "resolution": resolution,
            })
            raise GenerationEvidenceResolutionRequired(parsed, resolution)

        fingerprint = json.dumps(
            {
                "owner": parsed.get("owner"),
                "queries": parsed.get("queries"),
            },
            sort_keys=True,
            default=str,
        )
        if fingerprint in context["request_fingerprints"]:
            resolution = {
                "ok": False,
                "status": "repeated_evidence_request",
                "errors": [
                    "The same owner repeated an unchanged evidence request."
                ],
            }
            context["events"].append({
                "request": parsed,
                "resolution": resolution,
            })
            raise GenerationEvidenceResolutionRequired(parsed, resolution)
        context["request_fingerprints"].append(fingerprint)

        resolution = resolve_generation_evidence_request(
            parsed,
            project_root=context["project_root"],
            prior_evidence_ids=list(context["evidence_ids"]),
        )
        context["events"].append({
            "request": parsed,
            "resolution": resolution,
        })
        if not resolution.get("ok"):
            raise GenerationEvidenceResolutionRequired(parsed, resolution)

        new_evidence = list(resolution.get("new_evidence") or [])
        context["evidence_ids"].extend(
            str(item.get("evidence_id") or "")
            for item in new_evidence
            if str(item.get("evidence_id") or "")
        )
        evidence_json = json.dumps(
            {
                "schema": EVIDENCE_RESUME_SCHEMA,
                "owner": parsed.get("owner"),
                "new_evidence": new_evidence,
                "instruction": resolution.get("resume_instruction"),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        if isinstance(current_prompt, str):
            current_prompt = (
                current_prompt
                + "\n\nAUTHORITATIVE EVIDENCE RESUME PACKET\n"
                + evidence_json
                + "\n\nResume only the same owner. Return implementation code "
                "or another focused evidence_required request."
            )
        elif isinstance(current_prompt, list):
            current_prompt = [
                *current_prompt,
                {
                    "role": "user",
                    "content": (
                        "AUTHORITATIVE EVIDENCE RESUME PACKET\n"
                        + evidence_json
                        + "\nResume only the same owner."
                    ),
                },
            ]
        else:
            resolution = {
                **resolution,
                "ok": False,
                "status": "unsupported_generation_prompt_shape",
            }
            raise GenerationEvidenceResolutionRequired(parsed, resolution)
        current_response = invoke_model(current_prompt)
