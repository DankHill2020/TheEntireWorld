"""Discover and cache provider model identifiers without blocking the UI."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any


_CATALOG_CACHE: dict[str, tuple[float, tuple[str, ...]]] = {}
_CACHE_SECONDS = 900.0


def _request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Request one provider catalog document.

    :param url: Provider-owned model-list endpoint.
    :param headers: Optional authentication headers.
    :param timeout: Network timeout in seconds.
    :return: Parsed JSON object.
    """

    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", **dict(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _extract_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    """Extract model identifiers from common provider list shapes.

    :param payload: Provider model-list response.
    :return: Sorted unique model identifiers.
    """

    rows = payload.get("data") or payload.get("models") or []
    values: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, str):
            value = row
        elif isinstance(row, dict):
            value = str(row.get("id") or row.get("name") or "")
        else:
            value = ""
        value = value.removeprefix("models/").strip()
        if value:
            values.append(value)
    return tuple(sorted(set(values), key=str.lower))


def discover_provider_models(
    provider_id: str,
    *,
    api_key: str,
    timeout: float = 8.0,
    refresh: bool = False,
) -> tuple[str, ...]:
    """Return live model IDs for one configured cloud provider.

    :param provider_id: Tech Connector provider identifier.
    :param api_key: Provider API key.
    :param timeout: Network timeout in seconds.
    :param refresh: Whether to bypass the short-lived in-memory cache.
    :return: Discovered raw model identifiers.
    """

    provider = str(provider_id or "").strip().lower()
    key = str(api_key or "").strip()
    if not provider or not key:
        return ()
    cached = _CATALOG_CACHE.get(provider)
    if cached and not refresh and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]

    if provider == "openai":
        payload = _request_json(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    elif provider == "anthropic":
        payload = _request_json(
            "https://api.anthropic.com/v1/models?limit=1000",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            timeout=timeout,
        )
    elif provider == "google":
        payload = _request_json(
            "https://generativelanguage.googleapis.com/v1beta/models?"
            + urllib.parse.urlencode({"key": key, "pageSize": 1000}),
            timeout=timeout,
        )
    elif provider == "x":
        payload = _request_json(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    else:
        return ()
    values = _extract_ids(payload)
    _CATALOG_CACHE[provider] = (time.monotonic(), values)
    return values


def prefixed_catalog(provider_id: str, model_ids: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Prefix discovered IDs for Tech Connector's provider routing format.

    :param provider_id: Tech Connector provider identifier.
    :param model_ids: Raw provider model identifiers.
    :return: Prefixed unique model identifiers.
    """

    provider = str(provider_id or "").strip().lower()
    return tuple(
        f"{provider}:{value}"
        for value in dict.fromkeys(str(item).strip() for item in model_ids)
        if value
    )
