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
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from dcc_intelligence.runtime import elapsed_ms, iso_now, stage_result

try:
    from bridges.unreal.unreal_intelligence import ensure_project, open_store, resolve_project_root
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
        for row in rows:
            row["metadata"]["docs_version"] = self.version

        write_started = time.monotonic()
        api_count = self._write(rows)
        stages.append(stage_result("python_api_populated", api_count > 0, write_started, count=api_count))

        manifest = {
            "version": self.version,
            "source": index_url,
            "cached_at": iso_now(),
            "entries": len(rows),
            "enriched_pages": enriched,
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
