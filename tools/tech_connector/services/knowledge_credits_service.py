"""Persistent attribution for sources promoted into reusable knowledge."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from tech_connector.models.constants import APP_DIR
from tech_connector.services.open_knowledge_policy_service import (
    assess_open_knowledge_source,
)


SCHEMA_VERSION = 1
DEFAULT_CREDITS_PATH = APP_DIR / "intelligence" / "knowledge_credits.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalized_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.query,
            "",
        )
    )


def _credit_id(source: dict[str, Any]) -> str:
    identity = "|".join(
        (
            _normalized_url(source.get("url") or source.get("source_url") or ""),
            str(source.get("title") or source.get("name") or "").strip().lower(),
            str(source.get("creator") or source.get("author") or source.get("organization") or "").strip().lower(),
        )
    )
    return "knowledge-source-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _empty_registry() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": "open_information_only",
        "updated_at": "",
        "credits": [],
    }


def load_knowledge_credits(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = Path(path) if path else DEFAULT_CREDITS_PATH
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("policy", "open_information_only")
    data["credits"] = [row for row in data.get("credits", []) if isinstance(row, dict)]
    return data


def list_knowledge_credits(
    path: str | Path | None = None,
    *,
    query: str = "",
) -> list[dict[str, Any]]:
    rows = load_knowledge_credits(path).get("credits", [])
    query_text = str(query or "").strip().lower()
    if query_text:
        rows = [
            row
            for row in rows
            if query_text
            in " ".join(
                str(row.get(field) or "")
                for field in ("title", "creator", "organization", "url", "license", "what_learned", "domains")
            ).lower()
        ]
    return sorted(rows, key=lambda row: (str(row.get("creator") or "").lower(), str(row.get("title") or "").lower()))


def register_open_knowledge_sources(
    sources: list[dict[str, Any]],
    *,
    what_learned: str = "",
    domains: list[str] | None = None,
    evidence_packet_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Register eligible sources and reject anything outside the open policy."""

    registry_path = Path(path) if path else DEFAULT_CREDITS_PATH
    registry = load_knowledge_credits(registry_path)
    existing = {str(row.get("id") or ""): row for row in registry["credits"]}
    added: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    now = _utc_now()

    for raw_source in sources:
        source = dict(raw_source or {})
        assessment = assess_open_knowledge_source(source)
        if not assessment["eligible"]:
            rejected.append({**source, "knowledge_policy": assessment})
            continue
        credit_id = _credit_id(source)
        current = existing.get(credit_id)
        packet_ids = list(current.get("evidence_packet_ids") or []) if current else []
        if evidence_packet_id and evidence_packet_id not in packet_ids:
            packet_ids.append(evidence_packet_id)
        learned_values = list(current.get("learned_uses") or []) if current else []
        learned = str(source.get("what_learned") or what_learned or "").strip()
        if learned and learned not in learned_values:
            learned_values.append(learned)
        domain_values = list(current.get("domains") or []) if current else []
        for domain in list(source.get("domains") or []) + list(domains or []):
            value = str(domain or "").strip()
            if value and value not in domain_values:
                domain_values.append(value)

        row = {
            "id": credit_id,
            "title": str(source.get("title") or source.get("name") or "Untitled source").strip(),
            "creator": str(source.get("creator") or source.get("author") or "").strip(),
            "organization": str(source.get("organization") or source.get("publisher") or "").strip(),
            "url": assessment["url"],
            "license": str(source.get("license") or source.get("reuse_terms") or "Official public documentation").strip(),
            "attribution": str(source.get("attribution") or "").strip(),
            "what_learned": learned_values[-1] if learned_values else "",
            "learned_uses": learned_values,
            "domains": domain_values,
            "evidence_packet_ids": packet_ids,
            "first_used_at": str(current.get("first_used_at") or now) if current else now,
            "last_used_at": now,
            "knowledge_policy": assessment,
        }
        existing[credit_id] = row
        (updated if current else added).append(row)

    if added or updated:
        registry["credits"] = list(existing.values())
        registry["updated_at"] = now
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = registry_path.with_suffix(registry_path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
        temporary_path.replace(registry_path)

    return {
        "path": str(registry_path),
        "added": added,
        "updated": updated,
        "rejected": rejected,
        "total": len(existing),
    }

