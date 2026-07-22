"""Data-driven selection of reusable Unreal expert techniques."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "unreal_expert_techniques.json"


def load_expert_techniques(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = Path(path or REGISTRY_PATH)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "ai_studio.unreal_expert_techniques.v1":
        raise ValueError(f"Unsupported Unreal expert technique schema: {payload.get('schema')}")
    return payload


def select_expert_techniques(
    request: str,
    *,
    required_domains: Iterable[str] | None = None,
    project_context: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    payload = load_expert_techniques(path)
    registry_engine_version = str(payload.get("engine_version") or "")
    normalized = " ".join(re.findall(r"[a-z0-9_+.-]+", (request or "").lower()))
    required = {str(value) for value in required_domains or []}
    ranked = []
    for technique in payload.get("techniques") or []:
        technique = dict(technique)
        technique.setdefault("registry_engine_version", registry_engine_version)
        term_hits = sum(1 for term in technique.get("trigger_terms") or [] if str(term).lower() in normalized)
        domain_hits = len(required.intersection(str(value) for value in technique.get("domains") or []))
        if technique.get("always") or term_hits or (domain_hits and technique.get("domain_default")):
            ranked.append((100 if technique.get("always") else 0, domain_hits, term_hits, technique))
    ranked.sort(key=lambda row: (-row[0], -row[1], -row[2], str(row[3].get("key") or "")))
    techniques = [{**row, "match": {"domain_hits": domains, "term_hits": terms}} for _always, domains, terms, row in ranked]
    from tech_connector.services.unreal.technique_episode_store import match_technique_episodes

    matched_episodes = match_technique_episodes(
        request,
        technique_keys=[row.get("key") for row in techniques],
        project_context=project_context,
    )
    return {
        "framework": "unreal_expert_technique_selection_v1",
        "request": request,
        "required_domains": sorted(required),
        "techniques": techniques,
        "matched_verified_episodes": matched_episodes,
        "operations": list(
            dict.fromkeys(
                operation
                for technique in techniques
                for operation in technique.get("operations") or []
            )
        ),
        "sources": list(
            {
                str(source.get("url")): source
                for technique in techniques
                for source in technique.get("sources") or []
                if source.get("url")
            }.values()
        ),
    }
