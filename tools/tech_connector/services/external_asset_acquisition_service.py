"""Search and download external assets before host-specific ingest."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import mimetypes
import re
import time
import urllib.parse
import urllib.request
from typing import Any

from tech_connector.services.external_asset_destination_service import (
    canonical_host,
    normalize_asset_destination,
)
from tech_connector.services.public_https_service import create_public_https_context

MAX_ASSET_DOWNLOAD_BYTES = 512 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tga", ".bmp", ".exr", ".hdr"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac"}
MODEL_EXTENSIONS = {".fbx", ".obj", ".usd", ".usda", ".usdc", ".glb", ".gltf"}
PROVIDER_ACCOUNT_ALIASES = {
    "fab": "fab",
    "fab marketplace": "fab",
    "fab.com": "fab",
    "mixamo": "mixamo",
    "mixamo.com": "mixamo",
    "actorcore": "actorcore",
    "reallusion": "actorcore",
    "rokoko": "rokoko",
    "quixel": "quixel",
    "megascans": "quixel",
    "quixel.com": "quixel",
    "sketchfab": "sketchfab",
    "sketchfab.com": "sketchfab",
    "turbosquid": "turbosquid",
    "turbosquid.com": "turbosquid",
    "cgtrader": "cgtrader",
    "cgtrader.com": "cgtrader",
    "freesound": "freesound",
    "freesound.org": "freesound",
}


@dataclass(frozen=True)
class ExternalAssetCandidate:
    name: str
    provider: str
    url: str
    download_url: str = ""
    asset_type: str = "asset"
    license: str = ""
    formats: tuple[str, ...] = ()
    target_hosts: tuple[str, ...] = ()
    description: str = ""
    auth_required: bool = False
    download_available: bool = False
    account_id: str = ""
    login_url: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """
            Convert candidate to dict.
        :return: serializable candidate
        """
        return asdict(self)


def _tokens(text: str) -> set[str]:
    return {item for item in re.split(r"[^a-z0-9]+", text.lower()) if item}


def provider_account_id(provider: str = "", url: str = "") -> str:
    """
        Resolve provider account id.
    :param provider: provider display name
    :param url: source or download URL
    :return: connected account id or empty string
    """
    parsed = urllib.parse.urlparse(url or "")
    haystack = " ".join([provider or "", parsed.netloc or ""]).lower()
    for marker, account_id in PROVIDER_ACCOUNT_ALIASES.items():
        if marker in haystack:
            return account_id
    return ""


def provider_login_url(account_id: str) -> str:
    """
        Get provider login URL.
    :param account_id: connected account id
    :return: setup/login URL
    """
    if not account_id:
        return ""
    try:
        from tech_connector.services.connected_account_service import account_definition

        definition = account_definition(account_id)
        return definition.setup_url if definition else ""
    except Exception:
        return ""


def candidate_auth_status(candidate: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """
        Get candidate provider auth status.
    :param candidate: external asset candidate
    :param settings: application settings
    :return: provider account status for candidate
    """
    item = dict(candidate or {})
    account_id = str(item.get("account_id") or provider_account_id(str(item.get("provider") or ""), str(item.get("url") or item.get("download_url") or "")))
    requires_auth = bool(item.get("auth_required")) or bool(account_id and account_id not in {"poly_haven"})
    out = {
        "account_id": account_id,
        "requires_auth": requires_auth,
        "connected": not requires_auth,
        "mode": "public/no auth required" if not requires_auth else "not configured",
        "login_url": str(item.get("login_url") or provider_login_url(account_id)),
    }
    if requires_auth and account_id and settings is not None:
        try:
            from tech_connector.services.connected_account_service import connected_account_status

            status = connected_account_status(settings, account_id)
            out.update(
                {
                    "connected": bool(status.get("connected")),
                    "mode": str(status.get("mode") or ""),
                    "login_url": str(status.get("setup_url") or out["login_url"]),
                    "missing_fields": list(status.get("missing_fields") or []),
                }
            )
        except Exception as exc:
            out["mode"] = f"auth status unavailable: {exc}"
    return out


def _asset_type_from_url(url: str, fallback: str = "asset") -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "texture"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in MODEL_EXTENSIONS:
        return "model"
    if suffix == ".uasset":
        return "unreal_asset"
    return fallback or "asset"


def _direct_url_candidate(query: str, asset_type: str, target_host: str) -> dict[str, Any] | None:
    match = re.search(r"https?://[^\s\"')>]+", query or "", re.IGNORECASE)
    if not match:
        return None
    url = match.group(0).rstrip(".,")
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path or "")).name or parsed.netloc or "Direct Asset URL"
    suffix = Path(name).suffix.lower()
    inferred_type = _asset_type_from_url(url, asset_type or "asset")
    supported_download = suffix in IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | MODEL_EXTENSIONS | {".bvh", ".amc", ".asf", ".uasset", ".zip"}
    candidate = ExternalAssetCandidate(
        name=name,
        provider=parsed.netloc or "Direct URL",
        url=url,
        download_url=url,
        asset_type=inferred_type,
        license="User-provided URL; review required",
        formats=(suffix.lstrip("."),) if suffix else (),
        target_hosts=(canonical_host(target_host),) if target_host else (),
        description="Direct asset URL from the prompt or UI search box.",
        auth_required=False,
        download_available=supported_download,
        account_id=provider_account_id(parsed.netloc, url),
        login_url=provider_login_url(provider_account_id(parsed.netloc, url)),
        score=100.0,
    ).to_dict()
    if suffix in IMAGE_EXTENSIONS:
        candidate["thumbnail_url"] = url
    if not supported_download:
        candidate["candidate_status"] = "listing_or_page_requires_resolved_download_url"
    return candidate


def _candidate_from_source(key: str, source: dict[str, Any]) -> ExternalAssetCandidate:
    provides = tuple(str(item) for item in (source.get("provides") or ()))
    compatibility = source.get("compatibility") or {}
    account_id = provider_account_id(str(source.get("name") or key), str(source.get("url") or ""))
    return ExternalAssetCandidate(
        name=str(source.get("name") or key),
        provider=str(source.get("name") or key),
        url=str(source.get("url") or ""),
        asset_type="asset",
        license=str(source.get("license") or ""),
        formats=tuple(item for item in ("fbx", "uasset", "png", "wav") if item in provides),
        target_hosts=tuple(canonical_host(item) for item in compatibility.keys()),
        description=str(source.get("description") or ""),
        auth_required=bool(source.get("automation") in {"Manual", "Semi"}),
        download_available=False,
        account_id=account_id,
        login_url=provider_login_url(account_id),
        score=float(source.get("success_probability") or 0.0),
    )


def known_external_asset_sources() -> list[dict[str, Any]]:
    """
        List known external asset source candidates.
    :return: provider candidate dictionaries
    """
    try:
        from tech_connector.services.capability_acquisition_service import (
            KNOWN_CAPABILITY_SOURCES,
        )
    except Exception:
        return []
    candidates = []
    for key, source in KNOWN_CAPABILITY_SOURCES.items():
        if source.get("source_type") in {"asset_source", "marketplace"}:
            candidates.append(_candidate_from_source(key, source).to_dict())
    return candidates


def asset_provider_account_rows(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
        List 3D asset provider accounts.
    :param settings: application settings
    :return: connected account status rows for asset providers
    """
    try:
        from tech_connector.services.connected_account_service import (
            connected_account_status_rows,
        )

        return connected_account_status_rows(
            dict(settings or {}), categories={"3D Asset Providers"}
        )
    except Exception:
        return []


def active_external_asset_sources(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
        List external asset sources active for search.
    :param settings: application settings
    :return: public sources plus connected provider sources
    """
    active_accounts = {
        row["id"]
        for row in asset_provider_account_rows(settings)
        if row.get("connected")
    }
    active_sources = []
    for source in known_external_asset_sources():
        auth = candidate_auth_status(source, settings)
        account_id = str(auth.get("account_id") or source.get("account_id") or "")
        if not auth.get("requires_auth") or account_id in active_accounts:
            source = dict(source)
            source["active_for_search"] = True
            source["auth_status"] = auth
            active_sources.append(source)
    return active_sources


def requested_provider_account_ids(query: str) -> set[str]:
    """
        Get explicitly named provider accounts.
    :param query: search query from the prompt or UI
    :return: provider account ids named by the user
    """
    lower = str(query or "").lower()
    requested: set[str] = set()
    for marker, account_id in PROVIDER_ACCOUNT_ALIASES.items():
        if marker and marker in lower:
            requested.add(account_id)
    return requested


def _login_candidate_sources_for_request(
    query: str,
    asset_type: str,
    settings: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    requested_accounts = requested_provider_account_ids(query)
    lower = " ".join([query or "", asset_type or ""]).lower()
    wants_animation = bool(
        re.search(
            r"\b(anim|animation|motion|mocap|climb|climbing|retarget|skeleton|manny|fbx)\b",
            lower,
        )
    )
    candidates: list[dict[str, Any]] = []
    for source in known_external_asset_sources():
        auth = candidate_auth_status(source, settings)
        account_id = str(auth.get("account_id") or source.get("account_id") or "")
        if not auth.get("requires_auth") or auth.get("connected"):
            continue
        source_text = " ".join(
            str(source.get(key) or "")
            for key in ("name", "provider", "description", "asset_type")
        ).lower()
        is_relevant_animation_provider = wants_animation and bool(
            re.search(r"\b(anim|animation|motion|mocap|fbx|marketplace)\b", source_text)
        )
        if account_id in requested_accounts or is_relevant_animation_provider:
            row = dict(source)
            row["active_for_search"] = False
            row["login_required_for_search"] = True
            row["auth_status"] = auth
            candidates.append(row)
    return candidates


def search_asset_candidates(
    query: str,
    asset_type: str = "",
    target_host: str = "",
    providers: list[dict[str, Any]] | None = None,
    limit: int = 8,
    settings: dict[str, Any] | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """
        Search external asset candidates.
    :param query: search query from the user prompt
    :param asset_type: requested asset type such as animation, texture, audio, or mesh
    :param target_host: target DCC host
    :param providers: optional direct provider candidates used by tests or connector APIs
    :param limit: maximum candidates to return
    :param settings: application settings for provider auth state
    :param active_only: include only public or connected provider services
    :return: ranked candidate dictionaries
    """
    query_tokens = _tokens(" ".join([query, asset_type, target_host]))
    host = canonical_host(target_host)
    if providers is not None:
        raw_candidates = list(providers)
    elif active_only:
        raw_candidates = active_external_asset_sources(settings)
        known_keys = {
            str(item.get("account_id") or provider_account_id(str(item.get("provider") or ""), str(item.get("url") or "")))
            for item in raw_candidates
        }
        for login_source in _login_candidate_sources_for_request(query, asset_type, settings):
            account_id = str(login_source.get("account_id") or "")
            if account_id and account_id not in known_keys:
                raw_candidates.append(login_source)
                known_keys.add(account_id)
    else:
        raw_candidates = known_external_asset_sources()
    direct = _direct_url_candidate(query, asset_type, host)
    if direct:
        raw_candidates.insert(0, direct)
    ranked = []
    animation_roles: list[str] = []
    if "anim" in str(asset_type or "").lower() or "motion" in str(asset_type or "").lower():
        try:
            from tech_connector.services.unreal.animation_context_service import infer_animation_roles

            animation_roles = infer_animation_roles(query)
        except Exception:
            animation_roles = []
    for raw in raw_candidates:
        candidate = dict(raw or {})
        text = " ".join(
            str(candidate.get(key) or "")
            for key in ("name", "provider", "description", "asset_type", "license")
        )
        text += " " + " ".join(str(item) for item in candidate.get("formats") or ())
        text += " " + " ".join(str(item) for item in candidate.get("target_hosts") or ())
        overlap = len(query_tokens & _tokens(text))
        if asset_type and asset_type.lower() in str(candidate.get("asset_type") or "").lower():
            overlap += 2
        hosts = {canonical_host(item) for item in (candidate.get("target_hosts") or ())}
        if host and host != "auto" and (host in hosts or not hosts):
            overlap += 1
        base_score = float(candidate.get("score") or 0.0)
        score = overlap + base_score
        if score <= 0:
            continue
        candidate.setdefault("download_url", candidate.get("url") or "")
        candidate.setdefault("download_available", bool(candidate.get("download_url")))
        account_id = str(candidate.get("account_id") or provider_account_id(str(candidate.get("provider") or ""), str(candidate.get("url") or candidate.get("download_url") or "")))
        candidate["account_id"] = account_id
        candidate["login_url"] = str(candidate.get("login_url") or provider_login_url(account_id))
        candidate["auth_status"] = candidate_auth_status(candidate, settings)
        candidate["target_host"] = host
        if animation_roles:
            try:
                from tech_connector.services.unreal.animation_context_service import evaluate_animation_candidate

                semantic_rows = [evaluate_animation_candidate(role, candidate) for role in animation_roles]
                candidate["animation_context"] = semantic_rows
                accepted_rows = [row for row in semantic_rows if row.get("accepted")]
                if not accepted_rows:
                    candidate["contextually_usable"] = False
                    score -= 1000
                else:
                    candidate["contextually_usable"] = True
                    score += max(int(row.get("score") or 0) for row in accepted_rows)
            except Exception as exc:
                candidate["contextually_usable"] = False
                candidate["animation_context_error"] = str(exc)
                score -= 1000
        candidate["score"] = score
        ranked.append(candidate)
    ranked.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return ranked[: max(1, int(limit or 1))]


def _safe_filename(name: str, url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    url_name = Path(urllib.parse.unquote(parsed.path or "")).name
    raw = name or url_name or "asset"
    suffix = Path(url_name).suffix or mimetypes.guess_extension("") or ""
    stem = Path(raw).stem if Path(raw).suffix else raw
    clean_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "asset"
    clean_suffix = Path(raw).suffix or suffix
    return f"{clean_stem[:80]}{clean_suffix[:16]}"


def download_asset_candidate(
    candidate: dict[str, Any],
    cache_root: str | Path,
    approved: bool = False,
    target_host: str = "",
    destination: str = "",
    max_bytes: int = MAX_ASSET_DOWNLOAD_BYTES,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
        Download an approved external asset candidate.
    :param candidate: asset candidate with download_url, license, and provider data
    :param cache_root: local acquisition cache root
    :param approved: whether the user or policy approved this external download
    :param target_host: target DCC host for later ingest
    :param destination: target host destination for later ingest
    :param max_bytes: maximum accepted response size
    :return: download result with local file and manifest paths
    """
    started = time.monotonic()
    item = dict(candidate or {})
    download_url = str(item.get("download_url") or item.get("url") or "")
    result: dict[str, Any] = {
        "ok": False,
        "elapsed_ms": 0,
        "candidate": item,
        "local_path": "",
        "manifest_path": "",
        "bytes": 0,
        "sha256": "",
        "errors": [],
        "warnings": [],
        "requires_approval": not approved,
    }
    if not approved:
        result["errors"].append("External asset download requires approval.")
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result
    if item.get("contextually_usable") is False and not bool(item.get("probe_only", False)):
        result["errors"].append(
            "Asset candidate was rejected by the gameplay animation semantic contract."
        )
        result["semantic_evidence"] = item.get("animation_context") or []
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result
    auth = candidate_auth_status(item, settings)
    result["auth_status"] = auth
    if auth.get("requires_auth") and not auth.get("connected"):
        result["errors"].append(
            f"Provider login required for {auth.get('account_id') or item.get('provider') or 'this source'}."
        )
        result["requires_login"] = True
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result
    if not download_url:
        result["errors"].append("Candidate does not include a download_url.")
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result

    parsed = urllib.parse.urlparse(download_url)
    if parsed.scheme not in {"http", "https"}:
        result["errors"].append(f"Unsupported download scheme: {parsed.scheme or 'none'}")
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result

    cache = Path(cache_root).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(str(item.get("name") or ""), download_url)
    local_path = cache / filename
    manifest_path = cache / f"{local_path.stem}.provenance.json"

    request = urllib.request.Request(
        download_url, headers={"User-Agent": "TechConnectorAssetIngest/1.0"}
    )
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
            context=create_public_https_context(),
        ) as response:
            with open(local_path, "wb") as handle:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > int(max_bytes):
                        raise IOError(f"Asset download exceeded {max_bytes} bytes")
                    digest.update(chunk)
                    handle.write(chunk)
    except Exception as exc:
        result["errors"].append(str(exc))
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result

    host = canonical_host(target_host or item.get("target_host"))
    normalized_destination = normalize_asset_destination(host, destination)
    manifest = {
        "name": item.get("name") or local_path.name,
        "provider": item.get("provider") or "",
        "source_url": item.get("url") or download_url,
        "download_url": download_url,
        "license": item.get("license") or "",
        "asset_type": item.get("asset_type") or "asset",
        "target_host": host,
        "destination": normalized_destination,
        "local_path": str(local_path),
        "sha256": digest.hexdigest(),
        "bytes": downloaded,
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "review": {
            "approved": bool(approved),
            "auth_required": bool(item.get("auth_required", False)),
            "probe_only": bool(item.get("probe_only", False)),
        },
        "animation_context": item.get("animation_context") or [],
        "contextually_usable": item.get("contextually_usable"),
        "semantic_candidate_accepted_for_download": bool(
            item.get("semantic_candidate_accepted_for_download", False)
        ),
        "contextual_preview_status": str(item.get("contextual_preview_status") or "not_required"),
        "completion_allowed": bool(item.get("completion_allowed", False)),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result.update(
        {
            "ok": True,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "local_path": str(local_path),
            "manifest_path": str(manifest_path),
            "bytes": downloaded,
            "sha256": digest.hexdigest(),
            "requires_approval": False,
            "manifest": manifest,
        }
    )
    return result
