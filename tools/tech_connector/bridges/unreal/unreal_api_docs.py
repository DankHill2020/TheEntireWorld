"""Cache and index Unreal Python API documentation.

This intentionally stores compact lookup records, not a vendored copy of the
documentation in the application repo. Raw HTML cache files live under data/
for local use, while model context reads the parsed SQLite rows.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

APP_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_ROOT = next(
    candidate for candidate in APP_ROOT.parents if candidate.name.lower() == "tools"
)
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tech_connector.dcc_intelligence.runtime import elapsed_ms, iso_now, stage_result

try:
    from tech_connector.bridges.unreal.unreal_intelligence import ensure_project, open_store, resolve_project_root
except Exception:
    from unreal_intelligence import ensure_project, open_store, resolve_project_root


DEFAULT_VERSION = "5.8"
DEFAULT_BASE_URL = "https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/"
DEFAULT_CACHE_ROOT = APP_ROOT / "data" / "unreal_docs" / "cache"


@dataclass
class ApiDocEntry:
    qualified_name: str
    object_type: str
    url: str
    title: str = ""
    summary: str = ""
    signature: str = ""


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attr = dict(attrs)
            self._href = attr.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "nav"}:
            self._skip_depth += 1
        elif tag == "h1":
            self._in_h1 = True
            self._h1_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_h1:
            self._h1_parts.append(text)
        self.text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth and tag in {"script", "style", "nav"}:
            self._skip_depth -= 1
        elif tag == "h1" and self._in_h1:
            self.title = " ".join(self._h1_parts).strip()
            self._in_h1 = False

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


class ApiMemberParser(HTMLParser):
    """Extract authoritative class/member declarations from an Epic API page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.members: list[tuple[str, str, str]] = []
        self._qualified_name = ""
        self._parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "dt":
            return
        qualified_name = str(dict(attrs).get("id") or "").strip()
        if qualified_name.startswith("unreal."):
            self._qualified_name = qualified_name
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._qualified_name:
            value = " ".join(data.split())
            if value:
                self._parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "dt" or not self._qualified_name:
            return
        signature = " ".join(self._parts).replace(" ¶", "").strip()
        lowered = signature.casefold()
        if lowered.startswith("class "):
            object_type = "class"
        elif "(" in signature:
            object_type = "function"
        else:
            object_type = "property"
        self.members.append(
            (self._qualified_name, object_type, signature[:1000])
        )
        self._qualified_name = ""
        self._parts = []


_PARSED_MEMBER_CACHE: dict[
    tuple[str, str],
    tuple[tuple[int, int], list[dict[str, Any]]],
] = {}


def docs_url(version: str = DEFAULT_VERSION, base_url: str = DEFAULT_BASE_URL) -> str:
    return f"{base_url}?application_version={urllib.parse.quote(version)}"


def cache_dir(version: str, cache_root: str | Path | None = None) -> Path:
    return Path(cache_root or DEFAULT_CACHE_ROOT) / str(version)


def _cache_name(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix or ".html"
    return f"{digest}{suffix}"


def _fetch(url: str, target_dir: Path, timeout: float = 20.0, force: bool = False) -> tuple[str, bool]:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / _cache_name(url)
    if path.exists() and not force:
        return path.read_text(encoding="utf-8", errors="replace"), True
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Studio-Unreal-Docs-Indexer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    path.write_text(body, encoding="utf-8")
    return body, False


def _object_type_from_url(url: str, fallback: str = "api") -> str:
    lower = url.lower()
    if "/class/" in lower or "class" in lower:
        return "class"
    if "/struct/" in lower or "struct" in lower:
        return "struct"
    if "/enum/" in lower or "enum" in lower:
        return "enum"
    if "/delegate/" in lower or "delegate" in lower:
        return "delegate"
    if "/function/" in lower or "function" in lower:
        return "function"
    return fallback


def _entry_from_link(base: str, href: str, text: str) -> ApiDocEntry | None:
    label = html.unescape(text or "").strip()
    if not label.startswith("unreal."):
        return None
    absolute = urllib.parse.urljoin(base, href)
    label = label.replace("¶", "").strip()
    return ApiDocEntry(
        qualified_name=label,
        object_type=_object_type_from_url(absolute),
        url=absolute,
        title=label,
    )


def _parse_index(html_text: str, base: str) -> list[ApiDocEntry]:
    parser = LinkParser()
    parser.feed(html_text)
    entries: dict[str, ApiDocEntry] = {}
    for href, text in parser.links:
        entry = _entry_from_link(base, href, text)
        if entry:
            entries.setdefault(entry.qualified_name, entry)
    return list(entries.values())


def _page_details(html_text: str, fallback_name: str) -> tuple[str, str, str]:
    parser = TextParser()
    parser.feed(html_text)
    title = parser.title or fallback_name
    text = parser.text
    signature = ""
    sig_match = re.search(rf"({re.escape(fallback_name)}\s*\([^)]*\))", text)
    if sig_match:
        signature = sig_match.group(1)
    summary = ""
    marker = fallback_name.split(".")[-1]
    chunks = re.split(r"(?<=[.!?])\s+", text)
    for chunk in chunks:
        if marker in chunk and 40 <= len(chunk) <= 420:
            summary = chunk
            break
    if not summary:
        summary = " ".join(chunks[:2])[:420]
    return title[:240], summary[:900], signature[:500]


def _cached_member_rows(
    version: str,
    cache_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Parse locally cached Epic class pages into member-level API rows."""

    target_dir = cache_dir(version, cache_root)
    paths = list(target_dir.glob("*.html")) if target_dir.exists() else []
    fingerprint = (
        len(paths),
        max(
            (path.stat().st_mtime_ns for path in paths),
            default=0,
        ),
    )
    cache_key = (str(target_dir.resolve()), str(version))
    cached = _PARSED_MEMBER_CACHE.get(cache_key)
    if cached and cached[0] == fingerprint:
        return [dict(row) for row in cached[1]]

    rows_by_name: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            page_html = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parser = ApiMemberParser()
        parser.feed(page_html)
        for qualified_name, object_type, signature in parser.members:
            parts = qualified_name.split(".")
            if len(parts) < 2:
                continue
            owner = parts[1]
            source = (
                f"{DEFAULT_BASE_URL}class/{urllib.parse.quote(owner)}"
                f"?application_version={urllib.parse.quote(str(version))}"
            )
            row = {
                "qualified_name": qualified_name,
                "object_type": object_type,
                "signature": signature,
                "docstring": signature,
                "source": source,
                "tags": [
                    "unreal",
                    "python_api",
                    object_type,
                    "official_cached_member",
                ],
                "metadata": {
                    "docs_version": str(version),
                    "cached_at": iso_now(),
                    "cache_file": str(path),
                    "authoritative_signature": True,
                },
            }
            previous = rows_by_name.get(qualified_name)
            if previous is None or len(signature) > len(
                str(previous.get("signature") or "")
            ):
                rows_by_name[qualified_name] = row
    rows = list(rows_by_name.values())
    _PARSED_MEMBER_CACHE[cache_key] = (fingerprint, rows)
    return [dict(row) for row in rows]


def lookup_official_unreal_api(
    api_path: str,
    *,
    version: str = DEFAULT_VERSION,
    timeout: float = 20.0,
    cache_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Resolve an exact ``unreal.*`` chain from Epic's official class pages."""

    requested = str(api_path or "").strip()
    if not requested.startswith("unreal."):
        return None
    parts = re.findall(
        r"[A-Za-z_][A-Za-z0-9_]*",
        requested.removeprefix("unreal."),
    )
    if not parts:
        return None
    owner = parts[0]
    members = parts[1:]
    target_dir = cache_dir(version, cache_root)

    def class_page(class_name: str) -> tuple[str, str]:
        url = (
            f"{DEFAULT_BASE_URL}class/{urllib.parse.quote(class_name)}"
            f"?application_version={urllib.parse.quote(version)}"
        )
        page, _from_cache = _fetch(url, target_dir, timeout=timeout)
        parser = TextParser()
        parser.feed(page)
        return url, parser.text

    def member_signature(text: str, member: str) -> str:
        match = re.search(
            rf"(?:classmethod\s+)?{re.escape(member)}\s*\([^)]*\)"
            r"\s*(?:→|->)\s*"
            r"[^¶\n]{1,220}",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return " ".join(match.group(0).split())[:500]
        match = re.search(
            rf"(?:classmethod\s+)?{re.escape(member)}\s*\([^)]*\)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return " ".join(match.group(0).split())[:500]
        property_match = re.search(
            rf"\bproperty\s+({re.escape(member)})\b"
            r"(?:\s*:\s*[A-Za-z_][A-Za-z0-9_.\[\] |]*)?",
            text,
            flags=re.IGNORECASE,
        )
        return (
            " ".join(property_match.group(0).split())[:500]
            if property_match
            else ""
        )

    resolved_steps: list[str] = []
    try:
        if not members:
            url, text = class_page(owner)
            class_match = re.search(
                rf"class\s+unreal\.\s*{re.escape(owner)}"
                r"\s*(?:\([^)]*\))?",
                text,
                flags=re.IGNORECASE,
            )
            if not class_match:
                return None
            signature = " ".join(class_match.group(0).split())[:500]
            return {
                "qualified_name": requested,
                "resolved_owner": "unreal",
                "signature": signature,
                "source": url,
                "source_excerpt": signature,
                "provider": "epic_unreal_python_api",
                "provenance": f"official_epic_python_api_{version}",
                "confidence": "exact",
                "authoritative_signature": True,
            }
        for intermediate in members[:-1]:
            url, text = class_page(owner)
            signature = member_signature(text, intermediate)
            if not signature:
                return None
            resolved_steps.append(f"unreal.{owner}.{signature}")
            return_match = re.search(
                r"(?:→|->)\s*([A-Z][A-Za-z0-9_]*)",
                signature,
            )
            if not return_match:
                return None
            owner = return_match.group(1)

        member = members[-1]
        url, text = class_page(owner)
        signature = member_signature(text, member)
        if not signature:
            return None
        resolved_steps.append(f"unreal.{owner}.{signature}")
        canonical_member_match = re.match(
            r"property\s+([A-Za-z_][A-Za-z0-9_]*)",
            signature,
        )
        canonical_member = (
            canonical_member_match.group(1)
            if canonical_member_match
            else member
        )
        return {
            "qualified_name": requested,
            "canonical_qualified_name": (
                f"unreal.{owner}.{canonical_member}"
            ),
            "resolved_owner": f"unreal.{owner}",
            "signature": signature,
            "source": url,
            "source_excerpt": "\n".join(resolved_steps),
            "provider": "epic_unreal_python_api",
            "provenance": f"official_epic_python_api_{version}",
            "confidence": "exact",
            "authoritative_signature": True,
        }
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return None


def search_official_unreal_capabilities(
    text: str,
    *,
    version: str = DEFAULT_VERSION,
    limit: int = 12,
    timeout: float = 20.0,
    cache_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Discover relevant classes and members from Epic's official API index."""

    def tokens(value: str) -> set[str]:
        expanded = re.sub(
            r"(?<=[a-z0-9])(?=[A-Z])",
            " ",
            (value or "").replace("_", " "),
        )
        normalized: set[str] = set()
        for raw_token in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", expanded):
            token = raw_token.casefold()
            if token in {
                "add", "and", "class", "from", "python", "the",
                "unreal", "using", "with",
            }:
                continue
            normalized.add(token)
            if token.endswith("ing") and len(token) > 5:
                normalized.add(token[:-3])
                normalized.add(token[:-3] + "e")
            elif token.endswith("ed") and len(token) > 4:
                normalized.add(token[:-2])
                normalized.add(token[:-1])
            elif token.endswith("ies") and len(token) > 5:
                normalized.add(token[:-3] + "y")
            elif token.endswith("s") and len(token) > 4:
                normalized.add(token[:-1])
        return normalized

    query_tokens = tokens(text)
    if not query_tokens:
        return []
    action_tokens = {
        "apply", "build", "change", "connect", "convert", "copy", "create",
        "delete",
        "edit", "export", "find", "generate", "get", "import", "load",
        "make", "modify", "query", "read", "remove", "save", "set",
        "spawn", "update", "validate", "write",
    }
    owner_role_tokens = {
        "editor", "factory", "helper", "helpers", "library", "service",
        "subsystem", "tool", "tools", "utility",
    }
    has_action_intent = bool(query_tokens & action_tokens)
    subject_tokens = query_tokens - action_tokens - owner_role_tokens
    target_dir = cache_dir(version, cache_root)
    index_url = docs_url(version)
    try:
        index_html, _from_cache = _fetch(
            index_url,
            target_dir,
            timeout=timeout,
        )
    except (OSError, TimeoutError, urllib.error.URLError):
        return []
    entries = _parse_index(index_html, index_url)
    ranked_entries: list[tuple[int, ApiDocEntry]] = []
    for entry in entries:
        entry_tokens = tokens(entry.qualified_name)
        overlap = query_tokens & entry_tokens
        if overlap:
            score = len(overlap) * 10
            if has_action_intent and entry_tokens & owner_role_tokens:
                score += 12
            ranked_entries.append((score, entry))
    ranked_entries.sort(
        key=lambda item: (-item[0], len(item[1].qualified_name))
    )
    candidate_entries = list(ranked_entries[:24])
    candidate_names = {
        entry.qualified_name for _score, entry in candidate_entries
    }
    if has_action_intent:
        for role in sorted(owner_role_tokens):
            role_candidates = [
                item for item in ranked_entries
                if (
                    role in tokens(item[1].qualified_name)
                    and (
                        not subject_tokens
                        or subject_tokens & tokens(item[1].qualified_name)
                    )
                )
            ]
            for item in role_candidates[:2]:
                if item[1].qualified_name in candidate_names:
                    continue
                candidate_entries.append(item)
                candidate_names.add(item[1].qualified_name)
    concept_candidates = []
    for item in ranked_entries:
        entry_tokens = (
            tokens(item[1].qualified_name)
            - owner_role_tokens
            - {"new", "node", "object"}
        )
        if (
            1 < len(entry_tokens) <= 5
            and entry_tokens <= query_tokens
        ):
            concept_candidates.append(item)
    for item in concept_candidates[:32]:
        if item[1].qualified_name in candidate_names:
            continue
        candidate_entries.append(item)
        candidate_names.add(item[1].qualified_name)
    concept_first: list[tuple[int, ApiDocEntry]] = []
    concept_first_names: set[str] = set()
    for item in [*concept_candidates[:32], *candidate_entries]:
        if item[1].qualified_name in concept_first_names:
            continue
        concept_first.append(item)
        concept_first_names.add(item[1].qualified_name)
    candidate_entries = concept_first[:80]

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cached_ranked: list[tuple[int, dict[str, Any]]] = []
    for cached_row in _cached_member_rows(version, cache_root):
        qualified_name = str(cached_row.get("qualified_name") or "")
        searchable_tokens = tokens(
            " ".join([
                qualified_name,
                str(cached_row.get("signature") or ""),
                str(cached_row.get("docstring") or ""),
            ])
        )
        overlap = query_tokens & searchable_tokens
        if not overlap:
            continue
        score = len(overlap) * 10
        if has_action_intent and overlap & action_tokens:
            score += 15
        cached_ranked.append((score, cached_row))
    cached_ranked.sort(
        key=lambda item: (
            -item[0],
            len(str(item[1].get("qualified_name") or "")),
        )
    )
    for score, cached_row in cached_ranked[: max(12, limit)]:
        qualified_name = str(cached_row.get("qualified_name") or "")
        if not qualified_name or qualified_name in seen:
            continue
        seen.add(qualified_name)
        rows.append({
            "qualified_name": qualified_name,
            "owner_module": qualified_name.rsplit(".", 1)[0],
            "import_statement": "import unreal",
            "signature": str(cached_row.get("signature") or ""),
            "source_excerpt": str(cached_row.get("docstring") or "")[:2200],
            "path": str(cached_row.get("source") or ""),
            "provider": "official_public_api_research",
            "provenance": f"official_epic_python_api_{version}_cached_member",
            "confidence": "exact",
            "authoritative_signature": True,
            "relevance_score": score,
            "supports": ", ".join(sorted(
                query_tokens & tokens(
                    str(cached_row.get("qualified_name") or "")
                    + " "
                    + str(cached_row.get("signature") or "")
                )
            )),
        })
    for _score, entry in candidate_entries:
        try:
            page_html, _from_cache = _fetch(
                entry.url,
                target_dir,
                timeout=timeout,
            )
        except (OSError, TimeoutError, urllib.error.URLError):
            continue
        parser = TextParser()
        parser.feed(page_html)
        page_text = parser.text
        class_name = entry.qualified_name.rsplit(".", 1)[-1]
        class_signature = re.search(
            rf"\bclass\s+unreal\.{re.escape(class_name)}\s*\([^)]*\)",
            page_text,
            flags=re.IGNORECASE,
        )
        if entry.qualified_name not in seen:
            seen.add(entry.qualified_name)
            rows.append({
                "qualified_name": entry.qualified_name,
                "owner_module": "unreal",
                "import_statement": "import unreal",
                "signature": (
                    " ".join(class_signature.group(0).split())
                    if class_signature else ""
                ),
                "source_excerpt": entry.summary,
                "path": entry.url,
                "provider": "official_public_api_research",
                "provenance": f"official_epic_python_api_{version}",
                "confidence": "exact",
                "authoritative_signature": bool(class_signature),
                "supports": ", ".join(
                    sorted(query_tokens & tokens(entry.qualified_name))
                ),
            })
        member_matches = re.finditer(
            r"(?:classmethod\s+)?([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
            r"(?:\s*(?:→|->)\s*[^¶\n]{1,220})?",
            page_text,
            flags=re.IGNORECASE,
        )
        ranked_members: list[tuple[int, str, str]] = []
        for match in member_matches:
            member_name = match.group(1)
            overlap = query_tokens & tokens(member_name)
            if not overlap:
                continue
            ranked_members.append((
                len(overlap),
                member_name,
                " ".join(match.group(0).split())[:500],
            ))
        ranked_members.sort(key=lambda item: (-item[0], item[1]))
        for _member_score, member_name, signature in ranked_members[:6]:
            qualified = f"unreal.{class_name}.{member_name}"
            if qualified in seen:
                continue
            seen.add(qualified)
            rows.append({
                "qualified_name": qualified,
                "owner_module": f"unreal.{class_name}",
                "import_statement": "import unreal",
                "signature": signature,
                "source_excerpt": signature,
                "path": entry.url,
                "provider": "official_public_api_research",
                "provenance": f"official_epic_python_api_{version}",
                "confidence": "exact",
                "authoritative_signature": True,
                "supports": ", ".join(
                    sorted(query_tokens & tokens(member_name))
                ),
            })
            if len(rows) >= max(1, limit):
                return rows[:limit]
    return rows[:limit]


def _compact_rows(entries: Iterable[ApiDocEntry]) -> list[dict[str, Any]]:
    rows = []
    for entry in entries:
        rows.append({
            "qualified_name": entry.qualified_name,
            "object_type": entry.object_type,
            "signature": entry.signature,
            "docstring": entry.summary,
            "source": entry.url,
            "tags": ["unreal", "python_api", entry.object_type],
            "metadata": {
                "title": entry.title,
                "docs_version": None,
                "cached_at": iso_now(),
            },
        })
    return rows


class UnrealApiDocsCache:
    def __init__(self, project_root: str | None = None, version: str = DEFAULT_VERSION,
                 cache_root: str | Path | None = None):
        self.project_root = resolve_project_root(project_root)
        self.version = str(version)
        self.cache_path = cache_dir(self.version, cache_root)

    def refresh(self, *, max_pages: int = 0, force: bool = False) -> dict[str, Any]:
        """Download/cache docs and populate SQLite lookup rows.

        max_pages=0 indexes the API landing page only, which is fast and still
        gives excellent exact/prefix symbol lookup. Larger values enrich the
        first N pages with summaries/signatures.
        """
        started = time.monotonic()
        stages: list[dict[str, Any]] = []
        warnings: list[str] = []
        index_url = docs_url(self.version)

        try:
            stage_started = time.monotonic()
            index_html, index_from_cache = _fetch(index_url, self.cache_path, force=force)
            stages.append(stage_result("docs_index_cached" if index_from_cache else "docs_index_downloaded", True, stage_started))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            stages.append(stage_result("docs_index_downloaded", False, started, error=str(exc)))
            return self._result(started, stages, warnings + [str(exc)], [], 0, 0)

        parse_started = time.monotonic()
        entries = _parse_index(index_html, index_url)
        stages.append(stage_result("docs_symbols_parsed", bool(entries), parse_started, count=len(entries), error=None if entries else "No unreal.* docs links found."))

        enriched = 0
        if max_pages > 0:
            for entry in entries[:max_pages]:
                try:
                    page_html, _ = _fetch(entry.url, self.cache_path, force=force)
                    title, summary, signature = _page_details(page_html, entry.qualified_name)
                    entry.title = title
                    entry.summary = summary
                    entry.signature = signature
                    enriched += 1
                except Exception as exc:
                    warnings.append(f"{entry.qualified_name}: {exc}")
            stages.append(stage_result("docs_pages_enriched", True, time.monotonic(), count=enriched))

        rows = _compact_rows(entries)
        cached_member_rows = _cached_member_rows(
            self.version,
            self.cache_path.parent,
        )
        rows_by_name = {
            str(row.get("qualified_name") or ""): row for row in rows
        }
        for row in cached_member_rows:
            rows_by_name[str(row.get("qualified_name") or "")] = row
        rows = list(rows_by_name.values())
        for row in rows:
            row["metadata"]["docs_version"] = self.version

        write_started = time.monotonic()
        api_count = self._write(rows)
        stages.append(stage_result("python_api_populated", api_count > 0, write_started, count=api_count))
        stages.append(stage_result(
            "cached_api_members_materialized",
            True,
            write_started,
            count=len(cached_member_rows),
        ))

        manifest = {
            "version": self.version,
            "source": index_url,
            "cached_at": iso_now(),
            "entries": len(rows),
            "enriched_pages": enriched,
            "cached_member_entries": len(cached_member_rows),
            "project_root": str(self.project_root),
        }
        try:
            (self.cache_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception as exc:
            warnings.append(f"manifest write failed: {exc}")

        return self._result(started, stages, warnings, rows, api_count, enriched)

    def _write(self, rows: list[dict[str, Any]]) -> int:
        store = open_store(str(self.project_root))
        try:
            project = ensure_project(store, str(self.project_root))
            with store.conn:
                for row in rows:
                    store.conn.execute(
                        """
                        INSERT INTO python_api(project_id, dcc, qualified_name, object_type,
                                               signature, docstring, source, tags_json, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(project_id, dcc, qualified_name) DO UPDATE SET
                            object_type=excluded.object_type,
                            signature=excluded.signature,
                            docstring=excluded.docstring,
                            source=excluded.source,
                            tags_json=excluded.tags_json,
                            metadata_json=excluded.metadata_json
                        """,
                        (
                            project.id,
                            "Unreal",
                            row["qualified_name"],
                            row.get("object_type") or "unknown",
                            row.get("signature"),
                            row.get("docstring"),
                            row.get("source"),
                            json.dumps(row.get("tags") or [], ensure_ascii=False, sort_keys=True),
                            json.dumps(row.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    name = row["qualified_name"]
                    kind = row.get("object_type") or "api"
                    summary = row.get("docstring") or f"Unreal Python API {kind}: {name}"
                    short_name = name.rsplit(".", 1)[-1]
                    symbol_rows = [
                        (
                            project.id,
                            "Unreal",
                            f"api.{name}",
                            f"api.{name}".lower(),
                            "python_api",
                            name,
                            name,
                            row.get("source") or "",
                            summary,
                            json.dumps({"object_type": kind, "docs_version": self.version}, ensure_ascii=False, sort_keys=True),
                        ),
                        (
                            project.id,
                            "Unreal",
                            f"api.short.{short_name}",
                            f"api.short.{short_name}".lower(),
                            "python_api_alias",
                            short_name,
                            name,
                            row.get("source") or "",
                            summary,
                            json.dumps({"object_type": kind, "docs_version": self.version}, ensure_ascii=False, sort_keys=True),
                        ),
                    ]
                    for symbol_row in symbol_rows:
                        store.conn.execute(
                            """
                            INSERT INTO symbols(project_id, dcc, symbol_key, symbol_key_norm, symbol_kind,
                                                display_name, qualified_name, source_ref, summary, metadata_json, indexed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(project_id, dcc, symbol_kind, symbol_key_norm, source_ref) DO UPDATE SET
                                symbol_key=excluded.symbol_key,
                                display_name=excluded.display_name,
                                qualified_name=excluded.qualified_name,
                                summary=excluded.summary,
                                metadata_json=excluded.metadata_json,
                                indexed_at=CURRENT_TIMESTAMP
                            """,
                            symbol_row,
                        )
            return len(rows)
        finally:
            store.close()

    def status(self) -> dict[str, Any]:
        manifest_path = self.cache_path / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
        store = open_store(str(self.project_root))
        try:
            project = ensure_project(store, str(self.project_root))
            row = store.conn.execute(
                "SELECT COUNT(*) AS n FROM python_api WHERE project_id=? AND dcc=?",
                (project.id, "Unreal"),
            ).fetchone()
            return {
                "cache_path": str(self.cache_path),
                "manifest": manifest,
                "api_count": int(row["n"]) if row else 0,
            }
        finally:
            store.close()

    @staticmethod
    def _result(started: float, stages: list[dict[str, Any]], warnings: list[str],
                rows: list[dict[str, Any]], api_count: int, enriched: int) -> dict[str, Any]:
        return {
            "success": api_count > 0,
            "duration_ms": elapsed_ms(started),
            "stages": stages,
            "warnings": warnings[:20],
            "api_count": api_count,
            "parsed_count": len(rows),
            "enriched_pages": enriched,
            "sample": rows[:8],
        }


def refresh_unreal_api_docs(project_root: str | None = None, version: str = DEFAULT_VERSION,
                            max_pages: int = 0, force: bool = False) -> dict[str, Any]:
    return UnrealApiDocsCache(project_root, version=version).refresh(max_pages=max_pages, force=force)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cache and index Unreal Python API docs")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        refresh_unreal_api_docs(args.project_root, version=args.version, max_pages=args.max_pages, force=args.force),
        indent=2,
        default=str,
    ))
