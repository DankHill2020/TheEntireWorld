"""Resolve capability gaps through sourced APIs or reviewed acquisition.

This service is intentionally separate from code generation. It may discover a
callable, but it never invents one and never promotes an unreviewed code sample
into generation evidence.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


_OFFICIAL_DOMAINS = {
    "blender": ("docs.blender.org",),
    "maya": ("help.autodesk.com",),
    "motionbuilder": ("help.autodesk.com",),
    "qt": ("doc.qt.io",),
    "unreal": ("dev.epicgames.com",),
}
_DEPENDENCY_MARKERS = re.compile(
    r"\b(?:adapter|api|bridge|existing|internal|library|package|plugin|sdk|"
    r"toolkit|wrapper)\b",
    flags=re.IGNORECASE,
)
_COMPLEX_CAPABILITY_ACTIONS = {
    "bake", "convert", "decode", "encode", "export", "extract", "import",
    "process", "retarget", "sync", "track", "transcode",
}
_CALLABLE_PATTERN = re.compile(
    r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r"\s*\((?P<arguments>[^()\n]{0,800})\)"
)
_UNHELPFUL_CALLABLES = {
    "bool", "dict", "float", "int", "len", "list", "object", "set", "str",
    "tuple",
}


def _intent_requires_resolved_callable(intent: Mapping[str, Any]) -> bool:
    """Return whether planning needs an existing callable for this intent."""

    return bool(
        intent.get("hosts")
        or intent.get("explicit_symbols")
        or (
            str(intent.get("action") or "").casefold()
            in _COMPLEX_CAPABILITY_ACTIONS
            and bool(intent.get("object_terms"))
        )
        or _DEPENDENCY_MARKERS.search(str(intent.get("source_clause") or ""))
    )


def _intent_tokens(intent: Mapping[str, Any]) -> set[str]:
    values = [
        str(intent.get("action") or ""),
        *[str(value) for value in intent.get("object_terms") or []],
        *[str(value) for value in intent.get("hosts") or []],
        *[str(value) for value in intent.get("explicit_symbols") or []],
    ]
    return {
        token.casefold()
        for token in re.findall(
            r"[A-Za-z_][A-Za-z0-9_]{2,}",
            " ".join(values),
        )
    }


def _record_covers_intent(
    record: Mapping[str, Any],
    intent: Mapping[str, Any],
    intent_index: int,
) -> bool:
    """Return whether authoritative evidence proves the requested capability."""

    if not record.get("authoritative_signature"):
        return False
    linked_indexes = {
        int(value)
        for value in record.get("intent_indexes") or []
        if str(value).isdigit()
    }
    if intent_index in linked_indexes:
        return True

    haystack = " ".join(
        str(record.get(field) or "")
        for field in (
            "qualified_name",
            "signature",
            "source_excerpt",
            "supports",
            "query_links",
        )
    ).casefold()
    explicit = [
        str(value).casefold()
        for value in intent.get("explicit_symbols") or []
    ]
    if explicit and any(
        value == str(record.get("qualified_name") or "").casefold()
        or value in haystack
        for value in explicit
    ):
        return True

    tokens = _intent_tokens(intent)
    haystack_tokens = {
        token.casefold()
        for token in re.findall(
            r"[A-Za-z_][A-Za-z0-9_]{2,}",
            haystack,
        )
    }
    action = str(intent.get("action") or "").casefold()
    object_tokens = {
        str(value).casefold()
        for value in intent.get("object_terms") or []
    }
    return bool(
        action
        and action in haystack_tokens
        and (not object_tokens or object_tokens & haystack_tokens)
    )


def _focused_local_records(
    intent: Mapping[str, Any],
    intent_index: int,
) -> list[dict[str, Any]]:
    """Repeat catalog discovery with only one contextual intent."""

    from tech_connector.services.capability_resolution_service import (
        resolve_capabilities,
    )

    resolution = resolve_capabilities(
        str(intent.get("query") or intent.get("source_clause") or ""),
        limit=64,
    )
    results: list[dict[str, Any]] = []
    for raw_record in resolution.get("candidates") or []:
        record = dict(raw_record)
        if not record.get("authoritative_signature"):
            continue
        record["intent_indexes"] = [intent_index]
        record["supports"] = list(dict.fromkeys([
            *list(record.get("supports") or []),
            str(intent.get("source_clause") or ""),
        ]))
        record["query_links"] = list(dict.fromkeys([
            *list(record.get("query_links") or []),
            str(intent.get("query") or ""),
        ]))
        results.append(record)
    return results


def _relevant_local_provider_errors(
    errors: Iterable[Mapping[str, Any]],
    intents: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Return failures that prevent proving local search was exhaustive."""

    hosts = {
        str(host).casefold()
        for intent in intents
        for host in intent.get("hosts") or []
    }
    always_relevant = {
        "capability_catalog",
        "generated_overlay",
        "host_adapter_index",
        "project_index",
        "tools_index",
    }
    host_providers = {
        "qt": {"installed_packages", "installed_qt"},
        "unreal": {"dcc_catalog", "unreal_index"},
        "maya": {"dcc_catalog", "host_adapter_index"},
        "blender": {"dcc_catalog", "host_adapter_index"},
        "motionbuilder": {"dcc_catalog", "host_adapter_index"},
    }
    relevant = set(always_relevant)
    for host in hosts:
        relevant.update(host_providers.get(host, set()))
    return [
        {
            "provider": str(item.get("provider") or ""),
            "error": str(item.get("error") or ""),
        }
        for item in errors
        if str(item.get("provider") or "") in relevant
    ]


def _official_domains(intent: Mapping[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        domain
        for host in intent.get("hosts") or []
        for domain in _OFFICIAL_DOMAINS.get(str(host).casefold(), ())
    ))


def _official_callable_record(
    intent: Mapping[str, Any],
    intent_index: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, str]]]:
    """Find an exact callable signature in official public documentation."""

    domains = _official_domains(intent)
    if not domains:
        return None, [], []

    from tech_connector.services.knowledge_research_service import (
        extract_public_source_claims,
        search_public_sources,
    )

    query = str(intent.get("query") or intent.get("source_clause") or "")
    errors: list[dict[str, str]] = []
    try:
        search_result = search_public_sources(
            f"{query} Python API callable exact signature arguments",
            official_only=False,
            allowed_domains=domains,
            limit=6,
            timeout=10.0,
        )
        sources = list(search_result.get("candidates") or [])
        extraction = extract_public_source_claims(
            sources[:4],
            query=f"{query} exact Python callable signature",
            max_sources=4,
            timeout=10.0,
        )
    except Exception as exc:
        return None, [], [{
            "provider": "official_capability_discovery",
            "error": f"{type(exc).__name__}: {exc}",
        }]

    tokens = _intent_tokens(intent)
    ranked: list[tuple[int, str, str, str]] = []
    for claim in extraction.get("claims") or []:
        source = dict(claim.get("source") or {})
        source_url = str(source.get("url") or claim.get("url") or "")
        source_domain = urlsplit(source_url).netloc.casefold().split(":", 1)[0]
        if not any(
            source_domain == domain or source_domain.endswith("." + domain)
            for domain in domains
        ):
            continue
        supporting_quote = str(
            claim.get("supporting_quote") or claim.get("claim") or ""
        )
        for match in _CALLABLE_PATTERN.finditer(supporting_quote):
            qualified_name = match.group("name")
            if qualified_name.casefold() in _UNHELPFUL_CALLABLES:
                continue
            signature = match.group(0)
            callable_tokens = {
                token.casefold()
                for token in re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]{2,}",
                    qualified_name,
                )
            }
            score = len(tokens & callable_tokens) * 8
            action = str(intent.get("action") or "").casefold()
            if action and any(
                part.startswith(action) or action.startswith(part)
                for part in callable_tokens
            ):
                score += 10
            if any(
                str(symbol).casefold() in qualified_name.casefold()
                or qualified_name.casefold() in str(symbol).casefold()
                for symbol in intent.get("explicit_symbols") or []
            ):
                score += 30
            if score:
                ranked.append(
                    (score, qualified_name, signature, supporting_quote)
                )
    if not ranked:
        return None, sources, errors

    ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1].casefold()))
    _, qualified_name, signature, supporting_quote = ranked[0]
    matching_source = next(
        (
            dict(claim.get("source") or {})
            for claim in extraction.get("claims") or []
            if signature in str(
                claim.get("supporting_quote") or claim.get("claim") or ""
            )
        ),
        {},
    )
    source_url = str(matching_source.get("url") or "")
    record = {
        "qualified_name": qualified_name,
        "owner_module": (
            qualified_name.rsplit(".", 1)[0]
            if "." in qualified_name
            else ""
        ),
        "import_statement": "",
        "signature": signature,
        "source_excerpt": supporting_quote[:2200],
        "path": source_url,
        "provider": "official_unnamed_capability_discovery",
        "provenance": "official_document_exact_signature",
        "confidence": "exact",
        "authoritative_signature": True,
        "supports": [str(intent.get("source_clause") or "")],
        "query_links": [str(intent.get("query") or "")],
        "intent_indexes": [intent_index],
        "attribution": {
            "title": str(matching_source.get("title") or qualified_name),
            "creator": str(matching_source.get("publisher") or ""),
            "url": source_url,
            "license": "Official public documentation",
        },
    }
    try:
        from tech_connector.services.knowledge_credits_service import (
            register_open_knowledge_sources,
        )
        credit_result = register_open_knowledge_sources(
            [{
                **record["attribution"],
                "official_public_documentation": True,
                "public_access": True,
                "access": "public",
            }],
            what_learned=(
                f"Exact callable signature verified for {qualified_name}."
            ),
            domains=[
                *[str(value) for value in intent.get("hosts") or []],
                "capability_discovery",
            ],
        )
        record["attribution"]["credits_registry"] = str(
            credit_result.get("path") or ""
        )
    except Exception as exc:
        record["attribution"]["credits_error"] = (
            f"{type(exc).__name__}: {exc}"
        )
    return record, sources, errors


def _github_candidates(intent: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return source candidates only; candidates are not callable evidence."""

    from tech_connector.services.knowledge_research_service import (
        search_public_sources,
    )

    query = str(intent.get("query") or intent.get("source_clause") or "")
    try:
        result = search_public_sources(
            f"{query} Python implementation GitHub",
            official_only=False,
            allowed_domains=["github.com"],
            limit=5,
            timeout=10.0,
        )
    except Exception as exc:
        return [], [{
            "provider": "github_capability_discovery",
            "error": f"{type(exc).__name__}: {exc}",
        }]
    return [
        dict(item)
        for item in result.get("candidates") or []
        if "github.com" in str(item.get("url") or "").casefold()
    ], []


def _acquisition_request(
    intent: Mapping[str, Any],
    project_root: Path,
    public_candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a request for the existing reviewed acquisition workflow."""

    from tech_connector.services.capability_acquisition_service import (
        AcquisitionEngine,
    )
    from tech_connector.services.capability_registry import CapabilityRegistry

    registry_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "capability_registry.json"
    )
    engine = AcquisitionEngine(CapabilityRegistry(registry_path), project_root)
    requirement = str(
        intent.get("source_clause") or intent.get("query") or ""
    )
    strategies = [
        strategy
        for strategy in engine.discover_strategies([requirement])
        if strategy.source_type == "github"
    ]
    strategy = asdict(strategies[0]) if strategies else {}
    return {
        "status": "review_required",
        "reason": "No authoritative local, installed, plugin, or official API callable was found.",
        "intent": dict(intent),
        "strategy": strategy,
        "candidate_sources": [
            {
                "title": str(item.get("title") or item.get("name") or ""),
                "url": str(item.get("url") or ""),
                "license": str(item.get("license") or "Unknown"),
            }
            for item in public_candidates
        ],
        "next_action": {
            "action": "github_search",
            "args": {
                "query": str(intent.get("query") or requirement),
                "goal": requirement,
                "fallback_only": False,
                "require_license_review": True,
                "require_callable_verification": True,
                "require_attribution": True,
                "reindex_after_ingest": True,
            },
        },
        "resume_condition": (
            "A reviewed repository is ingested, credited, AST-verifies a matching "
            "callable, is indexed, and the original intent resolves authoritatively."
        ),
    }


def resolve_unnamed_capability_gaps(
    intents: Iterable[Mapping[str, Any]],
    evidence: Iterable[Mapping[str, Any]],
    *,
    project_root: str | Path,
    allow_online: bool,
    local_provider_errors: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Resolve dependency-like capability gaps without fabricating callables.

    :param intents: Typed capability intents extracted from the request.
    :param evidence: Existing local, installed, plugin, and API evidence.
    :param project_root: Active project boundary for acquisition planning.
    :param allow_online: Whether official web and GitHub discovery may run.
    :return: Exact official evidence, unresolved intents, and acquisition actions.
    """

    intent_rows = [dict(item) for item in intents]
    evidence_rows = [dict(item) for item in evidence]
    unresolved = [
        {**intent, "intent_index": index}
        for index, intent in enumerate(intent_rows)
        if _intent_requires_resolved_callable(intent)
        and not any(
            _record_covers_intent(record, intent, index)
            for record in evidence_rows
        )
    ]
    focused_local_evidence: list[dict[str, Any]] = []
    still_unresolved: list[dict[str, Any]] = []
    for unresolved_intent in unresolved:
        intent_index = int(unresolved_intent.get("intent_index") or 0)
        intent = {
            key: value
            for key, value in unresolved_intent.items()
            if key != "intent_index"
        }
        focused = _focused_local_records(intent, intent_index)
        if focused:
            focused_local_evidence.extend(focused)
        else:
            still_unresolved.append(unresolved_intent)
    unresolved = still_unresolved

    relevant_local_errors = _relevant_local_provider_errors(
        local_provider_errors,
        unresolved,
    )
    if relevant_local_errors:
        return {
            "evidence": focused_local_evidence,
            "unresolved_intents": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "intent_index"
                }
                for item in unresolved
            ],
            "acquisition_requests": [],
            "provider_errors": relevant_local_errors,
            "local_resolution_complete": False,
            "online_search_performed": False,
            "status": "local_resolution_incomplete",
        }

    if not allow_online:
        return {
            "evidence": focused_local_evidence,
            "unresolved_intents": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "intent_index"
                }
                for item in unresolved
            ],
            "acquisition_requests": [],
            "provider_errors": [],
            "local_resolution_complete": True,
            "online_search_performed": False,
            "status": "online_disabled",
        }

    official_evidence: list[dict[str, Any]] = list(focused_local_evidence)
    acquisition_requests: list[dict[str, Any]] = []
    provider_errors: list[dict[str, str]] = []
    still_unresolved = []
    for unresolved_intent in unresolved:
        intent_index = int(unresolved_intent.pop("intent_index"))
        official_record, _, errors = _official_callable_record(
            unresolved_intent,
            intent_index,
        )
        provider_errors.extend(errors)
        if official_record is not None:
            official_evidence.append(official_record)
            continue

        candidates, errors = _github_candidates(unresolved_intent)
        provider_errors.extend(errors)
        acquisition_requests.append(
            _acquisition_request(
                unresolved_intent,
                Path(project_root).expanduser().resolve(),
                candidates,
            )
        )
        still_unresolved.append(unresolved_intent)

    return {
        "evidence": official_evidence,
        "unresolved_intents": still_unresolved,
        "acquisition_requests": acquisition_requests,
        "provider_errors": provider_errors,
        "local_resolution_complete": True,
        "online_search_performed": bool(unresolved),
        "status": (
            "acquisition_required"
            if acquisition_requests
            else "resolved"
        ),
    }
