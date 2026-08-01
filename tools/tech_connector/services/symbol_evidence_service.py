"""Compose existing symbol providers into one provenance-bearing worker packet."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import importlib.util
import json
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from tech_connector.models.constants import TOOLS_ROOT, project_index_db_path


_HOST_PATTERNS = {
    "unreal": re.compile(r"\b(?:unreal|ue[45]|unreal engine)\b", re.IGNORECASE),
    "maya": re.compile(
        r"\b(?:maya(?:\.cmds|\.api\.openmaya|\.openmaya)?|cmds\.|mel\b)",
        re.IGNORECASE,
    ),
    "blender": re.compile(r"\b(?:blender|bpy)\b", re.IGNORECASE),
    "motionbuilder": re.compile(
        r"\b(?:motionbuilder|pyfbsdk|mobu)\b",
        re.IGNORECASE,
    ),
}
_HOST_MODULES = {
    "unreal": ("unreal",),
    "maya": ("maya.cmds", "maya.api.OpenMaya", "maya.OpenMaya"),
    "blender": ("bpy",),
    "motionbuilder": ("pyfbsdk",),
}
_SAFE_INSPECTION_ROOTS = {"PySide6", "PySide2", "PyQt6", "PyQt5"}
_DCC_CATALOG_CACHE: dict[str, Any] | None = None
_OFFICIAL_API_CACHE: dict[str, dict[str, Any]] = {}
_EVIDENCE_PACKET_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_EVIDENCE_PACKET_CACHE_LOCK = threading.Lock()
_EVIDENCE_PACKET_CACHE_LIMIT = 96
_STOP_WORDS = {
    "add", "an", "and", "class", "code", "create", "current", "file", "from",
    "function", "keep", "method", "module", "package", "previous", "return",
    "selected", "test", "tests", "the", "under", "using", "value", "with",
}


def _installed_stub_callable(
    module_name: str,
    owner_name: str,
    member_name: str,
) -> tuple[str, str, str]:
    """Return an exact callable signature from an installed package stub."""

    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return "", "", ""
    origin = Path(str((spec.origin if spec else "") or ""))
    candidates = [
        origin.with_suffix(".pyi"),
        origin.parent / f"{module_name.rsplit('.', 1)[-1]}.pyi",
    ]
    stub_path = next(
        (candidate for candidate in candidates if candidate.is_file()),
        None,
    )
    if stub_path is None:
        return "", "", ""
    try:
        source = stub_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(stub_path))
    except (OSError, SyntaxError, UnicodeError):
        return "", "", ""

    owner_node: ast.ClassDef | None = None
    if owner_name:
        owner_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == owner_name
            ),
            None,
        )
        search_nodes = owner_node.body if owner_node is not None else []
        target_name = member_name
    else:
        owner_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == member_name
            ),
            None,
        )
        search_nodes = owner_node.body if owner_node is not None else tree.body
        target_name = "__init__" if owner_node is not None else member_name

    target = next(
        (
            node
            for node in search_nodes
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target_name
        ),
        None,
    )
    if target is None:
        return "", "", str(stub_path)

    header = ast.unparse(target).splitlines()[0].strip()
    header = re.sub(r"^(?:async\s+)?def\s+", "", header).removesuffix(":")
    if owner_node is not None and not owner_name:
        header = re.sub(
            r"^__init__\(self,\s*/,\s*",
            f"{member_name}(",
            header,
        )
        header = re.sub(
            r"^__init__\(self(?:,\s*)?",
            f"{member_name}(",
            header,
        )
        header = re.sub(
            r"\)\s*->\s*None$",
            f") -> {member_name}",
            header,
        )
    excerpt = ast.get_source_segment(source, target) or ast.unparse(target)
    return header, excerpt[:1600], str(stub_path)


def _path_revision(path: Path) -> str:
    """Return a cheap revision token for an index or catalog file."""

    try:
        stat = path.stat()
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _evidence_packet_cache_key(
    text: str,
    *,
    root: Path,
    overlay: Iterable[tuple[str, str, str]],
    host: str | None,
    limit: int,
    allow_official_research: bool,
    capability_search: bool,
) -> str:
    """Key evidence by inputs plus persistent-index and generated-source revisions."""

    project_index = Path(project_index_db_path(root))
    tools_index = Path(project_index_db_path(TOOLS_ROOT))
    effective_index = project_index if project_index.exists() else tools_index
    root_scope = str(root) if project_index.exists() else "<unindexed-project>"
    try:
        from tech_connector.services.capability_resolution_service import (
            extract_capability_intents,
        )
        capability_scope = [
            {
                "action": intent.action,
                "objects": list(intent.object_terms),
                "hosts": list(intent.hosts),
                "symbols": list(intent.explicit_symbols),
                "constraints": list(intent.constraints),
                "query": intent.query,
            }
            for intent in extract_capability_intents(text)
        ]
    except Exception:
        capability_scope = []
    payload = {
        "evidence_contract": 2,
        "capability_scope": capability_scope,
        "text_fallback": (
            ""
            if capability_scope
            else " ".join(str(text or "").split())
        ),
        "root": root_scope,
        "host": str(host or "").strip().lower(),
        "limit": int(limit),
        "official": bool(allow_official_research),
        "capability": bool(capability_search),
        "project_index": _path_revision(project_index),
        "tools_index": _path_revision(tools_index),
        "overlay": [
            [
                str(path),
                hashlib.sha256(str(source).encode("utf-8")).hexdigest(),
            ]
            for path, _original, source in overlay
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _cached_evidence_packet(cache_key: str) -> dict[str, Any] | None:
    """Return an isolated cached packet while refreshing its LRU position."""

    with _EVIDENCE_PACKET_CACHE_LOCK:
        packet = _EVIDENCE_PACKET_CACHE.get(cache_key)
        if packet is not None:
            _EVIDENCE_PACKET_CACHE.move_to_end(cache_key)
            return copy.deepcopy(packet)
    cache_path = _persistent_evidence_cache_path(cache_key)
    try:
        packet = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(packet, dict):
        return None
    with _EVIDENCE_PACKET_CACHE_LOCK:
        _EVIDENCE_PACKET_CACHE[cache_key] = copy.deepcopy(packet)
        _EVIDENCE_PACKET_CACHE.move_to_end(cache_key)
    return copy.deepcopy(packet)


def _store_evidence_packet(
    cache_key: str,
    packet: dict[str, Any],
) -> dict[str, Any]:
    """Store an immutable snapshot and return an isolated caller copy."""

    with _EVIDENCE_PACKET_CACHE_LOCK:
        _EVIDENCE_PACKET_CACHE[cache_key] = copy.deepcopy(packet)
        _EVIDENCE_PACKET_CACHE.move_to_end(cache_key)
        while len(_EVIDENCE_PACKET_CACHE) > _EVIDENCE_PACKET_CACHE_LIMIT:
            _EVIDENCE_PACKET_CACHE.popitem(last=False)
    cache_path = _persistent_evidence_cache_path(cache_key)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(packet, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_path.replace(cache_path)
        cached_files = sorted(
            cache_path.parent.glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for stale_path in cached_files[_EVIDENCE_PACKET_CACHE_LIMIT:]:
            try:
                stale_path.unlink()
            except OSError:
                continue
    except OSError:
        pass
    return copy.deepcopy(packet)


def _persistent_evidence_cache_path(cache_key: str) -> Path:
    """Return a user-local cache path outside all indexed project roots."""

    import os
    import tempfile

    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_CACHE_HOME")
        or tempfile.gettempdir()
    )
    return (
        Path(base)
        / "TechConnector"
        / "cache"
        / "symbol_evidence"
        / f"{cache_key}.json"
    )


def detect_symbol_evidence_hosts(text: str) -> tuple[str, ...]:
    """Return hosts explicitly implied by a request, candidate, or failure."""

    source = str(text or "")
    return tuple(
        host for host, pattern in _HOST_PATTERNS.items() if pattern.search(source)
    )


def extract_symbol_evidence_queries(text: str, *, limit: int = 16) -> list[str]:
    """Extract symbol-shaped terms without treating arbitrary prose as an API."""

    source = str(text or "")
    values: list[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip().strip("`'\".,:;")
        if not value or value.lower() in _STOP_WORDS or value in values:
            return
        values.append(value)

    for value in re.findall(
        r"\b(?:unreal|maya\.cmds|maya\.api\.OpenMaya|maya\.OpenMaya|cmds|"
        r"bpy|pyfbsdk|PySide6|PySide2|PyQt6|PyQt5|"
        r"[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b",
        source,
    ):
        add(value)
    for value in re.findall(
        r"\b(?:class|from|import|inherit(?:ing)?\s+from)\s+"
        r"([A-Za-z_][A-Za-z0-9_.]*)",
        source,
        flags=re.IGNORECASE,
    ):
        add(value)
    for value in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(", source):
        add(value)
    # Bare capitalized prose is not symbol evidence. Preserve named owners only
    # when their role distinguishes them from ordinary request language.
    for value in re.findall(
        r"\b[A-Z][A-Za-z0-9_]*(?:Adapter|Bridge|Client|Dialog|Factory|"
        r"Generator|Manager|Service|Subsystem|Transport|Widget|Worker)\b",
        source,
    ):
        add(value)
    return values[: max(1, int(limit))]


def _capability_catalog_records(
    text: str,
    *,
    project_root: Path,
    limit: int,
) -> list[dict[str, Any]]:
    """Return catalog candidates plus authoritative indexed definitions."""

    try:
        from tech_connector.services.capability_resolution_service import (
            resolve_capabilities,
        )
        resolution = resolve_capabilities(text, limit=max(16, limit * 2))
    except Exception:
        return []
    candidates = [
        dict(item)
        for item in resolution.get("candidates") or []
        if isinstance(item, dict)
    ]
    expansion_queries = list(dict.fromkeys(
        value
        for candidate in candidates
        for value in [
            str(candidate.get("qualified_name") or ""),
            *[
                str(related)
                for relationship_values in (
                    candidate.get("capability_relationships") or {}
                ).values()
                for related in (
                    relationship_values
                    if isinstance(relationship_values, list)
                    else []
                )
            ],
        ]
        if value
    ))
    if not expansion_queries:
        return candidates
    expansion_text = "\n".join(expansion_queries[: max(16, limit * 2)])
    authoritative = _intelligence_records(
        expansion_text,
        project_root,
        limit=max(16, limit),
    )
    if project_root != TOOLS_ROOT:
        authoritative.extend(_intelligence_records(
            expansion_text,
            TOOLS_ROOT,
            limit=max(16, limit),
        ))
    return [*authoritative, *candidates]


def _host_adapter_capability_records(
    text: str,
    *,
    hosts: Iterable[str],
    project_root: Path,
    limit: int,
) -> list[dict[str, Any]]:
    """Return verified adapter members ranked by requested capability terms."""

    def normalized_identifier_terms(value: str) -> set[str]:
        terms: set[str] = set()
        for identifier in re.findall(
            r"[A-Za-z_][A-Za-z0-9_]+",
            str(value or ""),
        ):
            for token in identifier.replace("_", " ").split():
                normalized = token.casefold()
                if len(normalized) >= 3 and normalized not in _STOP_WORDS:
                    terms.add(normalized)
        return terms

    def terms_are_semantically_related(left: str, right: str) -> bool:
        if left == right:
            return True
        minimum_length = min(len(left), len(right))
        if minimum_length < 5:
            return False
        common_length = 0
        for left_character, right_character in zip(left, right):
            if left_character != right_character:
                break
            common_length += 1
        return common_length >= min(6, minimum_length)

    request_terms = normalized_identifier_terms(str(text or ""))
    weak_terms = {
        "check",
        "create",
        "execute",
        "get",
        "inspect",
        "list",
        "query",
        "read",
        "set",
        "use",
    }
    try:
        from tech_connector.knowledge.search import (
            SOURCE_ALL,
            search_index_owner_members,
            search_index_symbols,
        )
    except Exception:
        return []
    ranked: list[tuple[int, dict[str, Any]]] = []
    search_root = TOOLS_ROOT if project_root != TOOLS_ROOT else project_root
    for selected_host in sorted(set(str(value).casefold() for value in hosts)):
        adapter_name = f"{selected_host.title()}Adapter"
        try:
            owner_rows = search_index_symbols(
                [adapter_name],
                limit=8,
                active_path=str(search_root),
                class_bias=True,
                scope=SOURCE_ALL,
                project_roots=[str(search_root)],
                project_root=str(search_root),
            )
        except Exception:
            continue
        owner_row = next(
            (
                row
                for row in owner_rows
                if str(row.get("qualname") or row.get("name") or "")
                .rsplit(".", 1)[-1]
                == adapter_name
            ),
            None,
        )
        if not owner_row:
            continue
        owner_path = str(owner_row.get("path") or "")
        owner_qualname = str(
            owner_row.get("qualname") or owner_row.get("name") or adapter_name
        )
        try:
            members = search_index_owner_members(
                owner_qualname,
                owner_path=owner_path,
                limit=max(64, limit * 4),
                active_path=str(search_root),
                scope=SOURCE_ALL,
                project_roots=[str(search_root)],
                project_root=str(search_root),
            )
        except Exception:
            continue
        for member in members:
            member_qualname = str(
                member.get("qualname") or member.get("name") or ""
            )
            if not member_qualname:
                continue
            member_name = member_qualname.rsplit(".", 1)[-1]
            member_terms = normalized_identifier_terms(member_name)
            matched_member_terms = {
                member_term
                for member_term in member_terms
                if any(
                    terms_are_semantically_related(
                        member_term,
                        request_term,
                    )
                    for request_term in request_terms
                )
            }
            strong_overlap = matched_member_terms - weak_terms
            weak_overlap = matched_member_terms & weak_terms
            if not strong_overlap and not weak_overlap:
                continue
            score = 100 + (20 * len(strong_overlap)) + len(weak_overlap)
            member_path = str(member.get("path") or owner_path)
            module = str(member.get("module") or "") or _module_for_path(
                member_path,
                search_root,
            )
            qualified_name = ".".join(
                value for value in (module, member_qualname) if value
            )
            signature = str(member.get("signature") or "")
            record = {
                "qualified_name": qualified_name,
                "owner_module": module,
                "owner_qualname": owner_qualname,
                "import_statement": (
                    f"from {module} import {adapter_name}" if module else ""
                ),
                "signature": signature,
                "source_excerpt": str(
                    member.get("source") or member.get("docstring") or ""
                )[:1600],
                "path": member_path,
                "provider": "host_adapter_capability_index",
                "provenance": (
                    "knowledge_index_v2:host_scoped_owner_member"
                ),
                "confidence": "exact",
                "authoritative_signature": bool(signature),
                "relevance_score": score,
                "supports": [
                    "host=" + selected_host,
                    "capability_terms="
                    + ",".join(sorted(strong_overlap or weak_overlap)),
                ],
                "query_links": [],
                "kind": str(member.get("kind") or "method"),
                "access_kind": "callable",
                "owner_member": True,
            }
            ranked.append((score, record))
    ranked.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("qualified_name") or "").casefold(),
        )
    )
    return [record for _score, record in ranked[: max(1, limit)]]


def _module_for_path(path: str, project_root: Path) -> str:
    try:
        relative = Path(path).resolve().relative_to(project_root)
    except (OSError, ValueError):
        return ""
    if relative.suffix != ".py":
        return ""
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _overlay_records(
    queries: Iterable[str],
    generated_overlay: Iterable[tuple[str, str, str]],
    project_root: Path,
) -> list[dict[str, Any]]:
    terminals = {query.rsplit(".", 1)[-1].lower() for query in queries}
    records: list[dict[str, Any]] = []
    for path, _original, source in generated_overlay:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        module = _module_for_path(path, project_root)
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ) or node.name.lower() not in terminals:
                continue
            owner = next(
                (
                    parent.name
                    for parent in tree.body
                    if isinstance(parent, ast.ClassDef) and node in parent.body
                ),
                "",
            )
            records.append({
                "qualified_name": ".".join(
                    part for part in (module, owner, node.name) if part
                ),
                "owner_module": module,
                "import_statement": (
                    f"from {module} import {owner or node.name}" if module else ""
                ),
                "signature": ast.unparse(node).splitlines()[0],
                "source_excerpt": (
                    ast.get_source_segment(source, node) or ast.unparse(node)
                )[:1600],
                "path": path,
                "provider": "generated_overlay",
                "provenance": "current_unsaved_candidate",
                "confidence": "exact",
                "authoritative_signature": True,
            })
    return records


def _intelligence_records(
    text: str,
    project_root: Path,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Resolve intent terms, then expand matching owners to exact declarations."""

    try:
        from tech_connector.knowledge.search import (
            SOURCE_ALL,
            search_index_owner_members,
            search_index_symbols,
        )
    except Exception:
        return []

    queries = extract_symbol_evidence_queries(text, limit=max(32, limit * 4))
    request_tokens = {
        value.casefold()
        for value in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", str(text or ""))
        if len(value) >= 3 and value.casefold() not in _STOP_WORDS
    }
    records_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}

    def symbol_tokens(value: str) -> set[str]:
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
        return {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", expanded)
            if len(token) >= 2
        }

    def add_row(
        row: dict[str, Any],
        query: str = "",
        *,
        owner_member: bool = False,
    ) -> None:
        path = str(row.get("path") or "")
        qualname = str(row.get("qualname") or row.get("name") or "")
        if not qualname:
            return
        row_key = (
            path.casefold(),
            qualname.casefold(),
            int(row.get("start_line") or 0),
        )
        module = str(row.get("module") or "") or _module_for_path(
            path, project_root
        )
        qualified = ".".join(value for value in (module, qualname) if value)
        query_lower = str(query or "").casefold()
        query_tail = query_lower.rsplit(".", 1)[-1]
        exact = bool(
            owner_member
            or (
                query_lower
                and (
                    qualname.casefold() == query_lower
                    or qualname.casefold().endswith("." + query_tail)
                    or qualified.casefold() == query_lower
                    or qualified.casefold().endswith("." + query_lower)
                )
            )
        )
        source_text = str(row.get("source") or "")
        raw_decorators = row.get("decorators") or row.get(
            "decorators_json"
        ) or []
        if isinstance(raw_decorators, str):
            try:
                raw_decorators = json.loads(raw_decorators)
            except (TypeError, ValueError):
                raw_decorators = [raw_decorators]
        decorators = [
            str(value)
            for value in raw_decorators
            if str(value)
        ]
        access_kind = (
            "property"
            if any(
                value.rsplit(".", 1)[-1] == "property"
                for value in decorators
            )
            or re.search(
                r"(?m)^\s*@(?:[A-Za-z_][A-Za-z0-9_]*\.)?property\s*$",
                source_text,
            )
            else "callable"
        )
        existing = records_by_key.get(row_key)
        if existing is not None:
            if query and query not in existing["query_links"]:
                existing["query_links"].append(query)
                existing["supports"].append(query)
            if exact:
                existing["provider"] = "project_index_definition"
                existing["confidence"] = "exact"
                existing["authoritative_signature"] = bool(
                    existing.get("signature")
                )
            existing["owner_member"] = bool(
                existing.get("owner_member") or owner_member
            )
            if access_kind == "property":
                existing["access_kind"] = "property"
            return
        top_owner = qualname.split(".", 1)[0]
        query_links = [query] if query else []
        records_by_key[row_key] = {
            "qualified_name": qualified,
            "owner_module": module,
            "owner_qualname": str(row.get("parent_qualname") or ""),
            "import_statement": (
                f"from {module} import {top_owner}"
                if module and top_owner else ""
            ),
            "signature": str(row.get("signature") or ""),
            "source_excerpt": source_text[:1600],
            "access_kind": access_kind,
            "decorators": decorators,
            "path": path,
            "kind": str(row.get("kind") or ""),
            "provider": (
                "project_index_definition"
                if exact else "project_index_usage_candidate"
            ),
            "provenance": (
                "knowledge_index_v2:"
                + str(row.get("source_scope") or "unknown")
            ),
            "confidence": "exact" if exact else "candidate",
            "authoritative_signature": bool(exact and row.get("signature")),
            "owner_member": owner_member,
            "query_links": query_links,
            "supports": list(query_links),
        }

    for query in queries:
        try:
            rows = search_index_symbols(
                [query],
                limit=min(max(limit * 2, 16), 32),
                active_path=str(project_root),
                class_bias=True,
                scope=SOURCE_ALL,
                project_roots=[str(project_root)],
                project_root=str(project_root),
            )
        except Exception:
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            add_row(row, query)

    owner_rows: list[dict[str, Any]] = []
    for record in records_by_key.values():
        if str(record.get("kind") or "").casefold() != "class":
            continue
        owner_name = str(record.get("qualified_name") or "").rsplit(".", 1)[-1]
        owner_terms = symbol_tokens(owner_name)
        linked_terms = {
            token
            for query in record.get("query_links") or []
            for token in symbol_tokens(str(query))
        }
        if (
            owner_name.casefold() in str(text or "").casefold()
            or len(owner_terms & request_tokens) >= 2
            or (
                owner_terms & request_tokens
                and owner_terms & linked_terms
            )
        ):
            owner_rows.append(record)

    for owner_record in owner_rows[: max(8, limit)]:
        qualified_name = str(owner_record.get("qualified_name") or "")
        module = str(owner_record.get("owner_module") or "")
        owner_qualname = (
            qualified_name[len(module) + 1 :]
            if module and qualified_name.startswith(module + ".")
            else qualified_name
        )
        try:
            members = search_index_owner_members(
                owner_qualname,
                owner_path=str(owner_record.get("path") or ""),
                limit=max(16, limit * 2),
                active_path=str(project_root),
                scope=SOURCE_ALL,
                project_roots=[str(project_root)],
                project_root=str(project_root),
            )
        except Exception:
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            member_terms = symbol_tokens(
                str(member.get("qualname") or member.get("name") or "")
            )
            linked_queries = [
                query
                for query in queries
                if member_terms & symbol_tokens(query)
            ]
            if linked_queries:
                for query in linked_queries:
                    add_row(member, query, owner_member=True)
            else:
                add_row(member, owner_member=True)
        class_header = str(
            owner_record.get("source_excerpt") or ""
        ).splitlines()[:1]
        base_names = (
            re.findall(
                r"\bclass\s+[A-Za-z_][A-Za-z0-9_]*\s*\(([^)]*)\)",
                class_header[0],
            )
            if class_header
            else []
        )
        for base_list in base_names:
            for base_name in [
                value.strip().rsplit(".", 1)[-1]
                for value in base_list.split(",")
                if value.strip()
            ]:
                try:
                    base_rows = search_index_symbols(
                        [base_name],
                        limit=8,
                        active_path=str(project_root),
                        class_bias=True,
                        scope=SOURCE_ALL,
                        project_roots=[str(project_root)],
                        project_root=str(project_root),
                    )
                except Exception:
                    continue
                base_class = next(
                    (
                        row
                        for row in base_rows
                        if isinstance(row, dict)
                        and str(row.get("kind") or "").casefold() == "class"
                        and str(row.get("qualname") or "").rsplit(".", 1)[-1]
                        == base_name
                    ),
                    None,
                )
                if not base_class:
                    continue
                try:
                    inherited_members = search_index_owner_members(
                        str(base_class.get("qualname") or base_name),
                        owner_path=str(base_class.get("path") or ""),
                        limit=max(16, limit * 2),
                        active_path=str(project_root),
                        scope=SOURCE_ALL,
                        project_roots=[str(project_root)],
                        project_root=str(project_root),
                    )
                except Exception:
                    continue
                for inherited_member in inherited_members:
                    if not isinstance(inherited_member, dict):
                        continue
                    member_name = str(
                        inherited_member.get("qualname")
                        or inherited_member.get("name")
                        or ""
                    ).rsplit(".", 1)[-1]
                    if not member_name:
                        continue
                    inherited_alias = dict(inherited_member)
                    inherited_alias.update({
                        "qualname": f"{owner_qualname}.{member_name}",
                        "parent_qualname": owner_qualname,
                        "path": str(owner_record.get("path") or ""),
                        "source_scope": str(
                            base_class.get("source_scope") or "project"
                        ),
                        "source": (
                            f"# Inherited from {base_name}\n"
                            + str(inherited_member.get("source") or "")
                        ),
                    })
                    add_row(
                        inherited_alias,
                        f"{owner_qualname}.{member_name}",
                        owner_member=True,
                    )

    records = list(records_by_key.values())
    records.sort(key=lambda item: (
        0 if item.get("owner_member") and item.get("signature") else 1,
        0 if item.get("provider") == "project_index_definition" else 1,
        -len(item.get("query_links") or []),
        str(item.get("qualified_name") or "").casefold(),
    ))
    return records[: max(32, min(72, limit * 6))]


def _installed_records(
    queries: Iterable[str], *, limit: int
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for query in queries:
        if "." not in query and re.fullmatch(r"Q[A-Z][A-Za-z0-9_]+", query):
            resolved_qt = False
            for binding in ("PySide6", "PySide2", "PyQt6", "PyQt5"):
                try:
                    if importlib.util.find_spec(binding) is None:
                        continue
                except (ImportError, ModuleNotFoundError, ValueError):
                    continue
                for qt_module in ("QtWidgets", "QtCore", "QtGui"):
                    module_name = f"{binding}.{qt_module}"
                    try:
                        module = importlib.import_module(module_name)
                        value = getattr(module, query)
                    except (
                        ImportError,
                        AttributeError,
                        ModuleNotFoundError,
                        RuntimeError,
                        ValueError,
                    ):
                        continue
                    signature = (
                        getattr(value, "__text_signature__", "") or ""
                    )
                    spec = importlib.util.find_spec(module_name)
                    records.append({
                        "qualified_name": f"{module_name}.{query}",
                        "owner_module": module_name,
                        "import_statement": (
                            f"from {module_name} import {query}"
                        ),
                        "signature": signature,
                        "source_excerpt": "",
                        "path": str((spec.origin if spec else "") or ""),
                        "provider": "installed_package_inspection",
                        "provenance": f"importlib:{module_name}",
                        "confidence": "exact",
                        "authoritative_signature": True,
                    })
                    resolved_qt = True
                    break
                if resolved_qt:
                    break
            if resolved_qt:
                if len(records) >= limit:
                    break
                continue
        parts = query.split(".")
        if not parts or parts[0] not in _SAFE_INSPECTION_ROOTS:
            continue
        module_name = ".".join(parts[:-1]) if len(parts) > 1 else parts[0]
        symbol_name = parts[-1] if len(parts) > 1 else ""
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                continue
            if symbol_name:
                module = importlib.import_module(module_name)
                value = getattr(module, symbol_name)
                signature = getattr(value, "__text_signature__", "") or ""
            else:
                signature = ""
        except (ImportError, AttributeError, ModuleNotFoundError, RuntimeError, ValueError):
            continue
        records.append({
            "qualified_name": query,
            "owner_module": module_name,
            "import_statement": (
                f"from {module_name} import {symbol_name}"
                if symbol_name else f"import {module_name}"
            ),
            "signature": signature,
            "source_excerpt": "",
            "path": str(spec.origin or ""),
            "provider": "installed_package_inspection",
            "provenance": f"importlib:{module_name}",
            "confidence": "exact",
            "authoritative_signature": bool(signature),
        })
        if len(records) >= limit:
            break
    return records


def _installed_qt_capability_records(
    text: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Search real installed Qt members when prose names behavior, not symbols."""

    source = str(text or "")
    if not re.search(r"\b(?:PySide|PyQt|Qt|Q[A-Z])", source):
        return []
    separated_source = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", source)
    source_term_counts: dict[str, int] = {}
    for raw_term in re.findall(
        r"[A-Za-z][A-Za-z0-9_]{2,}",
        separated_source,
    ):
        term = raw_term.casefold()
        if term in _STOP_WORDS:
            continue
        source_term_counts[term] = source_term_counts.get(term, 0) + 1
        if term.endswith("s") and len(term) > 3:
            singular = term[:-1]
            source_term_counts[singular] = (
                source_term_counts.get(singular, 0) + 1
            )
    source_terms = set(source_term_counts)
    capability_expansions = {
        "sample": {"pixel", "color", "image", "grab"},
        "capture": {"grab", "screen", "image", "window"},
        "desktop": {"screen", "geometry"},
        "screen": {"screen", "geometry", "window"},
        "pixel": {"pixel", "pixmap", "color", "image"},
        "cursor": {"cursor", "position", "pos"},
        "click": {"mouse", "button", "press", "position", "global"},
        "clicked": {"mouse", "button", "press", "position", "global"},
        "clicking": {"mouse", "button", "press", "position", "global"},
        "continuous": {"timer", "timeout", "interval"},
        "continuously": {"timer", "timeout", "interval"},
        "worker": {"thread", "runnable", "pool", "start", "run"},
        "thread": {"thread", "runnable", "pool", "start", "run"},
        "threadpool": {"thread", "pool", "start", "run"},
        "runnable": {"runnable", "thread", "pool", "start", "run"},
        "signal": {"signal", "connect", "emit"},
        "signals": {"signal", "connect", "emit"},
        "completion": {"signal", "finished", "connect", "emit"},
        "error": {"signal", "connect", "emit"},
        "escape": {"key", "event"},
        "preview": {"color", "text", "style"},
    }
    expanded_terms = set(source_terms)
    for term in source_terms:
        expanded_terms.update(capability_expansions.get(term, set()))

    def symbol_terms(value: str) -> set[str]:
        normalized_value = re.sub(
            r"^Q(?=[A-Z])",
            "",
            str(value or ""),
        )
        separated = re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1 \2",
            normalized_value,
        )
        return {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", separated)
            if token.casefold() not in {"abstract", "gui", "qt"}
        }

    ranked: list[tuple[int, dict[str, Any]]] = []
    requires_worker_bundle = bool(re.search(
        r"\b(?:worker|thread|threadpool|runnable|blocking)\b",
        source,
        flags=re.IGNORECASE,
    ))
    for binding in ("PySide6", "PySide2", "PyQt6", "PyQt5"):
        try:
            if importlib.util.find_spec(binding) is None:
                continue
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
        if requires_worker_bundle:
            module_name = f"{binding}.QtCore"
            try:
                qt_core = importlib.import_module(module_name)
                spec = importlib.util.find_spec(module_name)
                exact_worker_values = [
                    ("QThread", "start", getattr(qt_core.QThread, "start")),
                    ("", "Signal", getattr(qt_core, "Signal")),
                ]
            except (
                AttributeError,
                ImportError,
                ModuleNotFoundError,
                RuntimeError,
                ValueError,
            ):
                exact_worker_values = []
                spec = None
            for owner_name, member_name, member_value in exact_worker_values:
                (
                    signature,
                    source_excerpt,
                    evidence_path,
                ) = _installed_stub_callable(
                    module_name,
                    owner_name,
                    member_name,
                )
                if not signature:
                    signature = (
                        getattr(member_value, "__text_signature__", "") or ""
                    )
                    if not signature:
                        documentation_lines = str(
                            getattr(member_value, "__doc__", "") or ""
                        ).splitlines()
                        signature = (
                            documentation_lines[0]
                            if documentation_lines
                            else ""
                        )
                qualified_name = ".".join(
                    value
                    for value in (module_name, owner_name, member_name)
                    if value
                )
                import_name = owner_name or member_name
                ranked.append((
                    1000,
                    {
                        "qualified_name": qualified_name,
                        "owner_module": module_name,
                        "import_statement": (
                            f"from {module_name} import {import_name}"
                        ),
                        "signature": signature,
                        "source_excerpt": source_excerpt,
                        "path": (
                            evidence_path
                            or str((spec.origin if spec else "") or "")
                        ),
                        "provider": (
                            "installed_package_stub"
                            if evidence_path and signature
                            else "installed_package_capability_search"
                        ),
                        "provenance": (
                            (
                                f"stub:{evidence_path}"
                                if evidence_path and signature
                                else f"reflection:{module_name}:required_worker_bundle"
                            )
                        ),
                        "confidence": "exact",
                        "authoritative_signature": bool(signature),
                        "supports": [
                            "worker",
                            "thread",
                            "signal",
                        ],
                        "relevance_score": 1000,
                        "kind": "method" if owner_name else "class",
                        "access_kind": "callable",
                    },
                ))
        for qt_module in ("QtGui", "QtCore", "QtWidgets"):
            module_name = f"{binding}.{qt_module}"
            try:
                module = importlib.import_module(module_name)
                spec = importlib.util.find_spec(module_name)
            except (ImportError, ModuleNotFoundError, RuntimeError, ValueError):
                continue
            for class_name in dir(module):
                if not re.fullmatch(
                    r"Q[A-Z][A-Za-z0-9_]+|Signal|SignalInstance|Slot",
                    class_name,
                ):
                    continue
                try:
                    class_value = getattr(module, class_name)
                except (AttributeError, RuntimeError):
                    continue
                class_overlap = symbol_terms(class_name) & expanded_terms
                class_terms = symbol_terms(class_name)
                if not class_overlap or class_terms - expanded_terms:
                    continue
                class_original_overlap = class_overlap & source_terms
                class_unmatched_terms = (
                    symbol_terms(class_name) - expanded_terms
                )
                class_relevance = max(
                    1,
                    12 * sum(
                        source_term_counts.get(term, 0)
                        for term in class_original_overlap
                    )
                    + 2 * len(class_overlap - source_terms)
                    - 3 * len(class_unmatched_terms),
                )
                if class_overlap:
                    class_signature = (
                        getattr(class_value, "__text_signature__", "") or ""
                    )
                    if not class_signature:
                        class_documentation = str(
                            getattr(class_value, "__doc__", "") or ""
                        ).splitlines()
                        class_signature = (
                            class_documentation[0]
                            if class_documentation
                            else ""
                        )
                    ranked.append((
                        class_relevance,
                        {
                            "qualified_name": f"{module_name}.{class_name}",
                            "owner_module": module_name,
                            "import_statement": f"from {module_name} import {class_name}",
                            "signature": class_signature,
                            "source_excerpt": "",
                            "path": str((spec.origin if spec else "") or ""),
                            "provider": "installed_package_capability_search",
                            "provenance": f"reflection:{module_name}",
                            "confidence": "exact",
                            "authoritative_signature": True,
                            "supports": ", ".join(sorted(class_overlap)),
                            "relevance_score": class_relevance,
                        },
                    ))
                declared_members = getattr(class_value, "__dict__", {})
                for member_name in declared_members:
                    if member_name.startswith("_"):
                        continue
                    try:
                        member_value = getattr(class_value, member_name)
                    except (AttributeError, RuntimeError):
                        continue
                    member_overlap = symbol_terms(member_name) & expanded_terms
                    if not member_overlap:
                        continue
                    if not callable(member_value):
                        continue
                    unmatched_member_terms = (
                        symbol_terms(member_name) - expanded_terms
                    )
                    member_original_overlap = member_overlap & source_terms
                    relevance_score = max(
                        1,
                        class_relevance
                        + 8 * sum(
                            source_term_counts.get(term, 0)
                            for term in member_original_overlap
                        )
                        + 4 * len(member_overlap - source_terms)
                        - 2 * len(unmatched_member_terms),
                    )
                    signature = (
                        getattr(member_value, "__text_signature__", "") or ""
                    )
                    if not signature:
                        documentation_lines = str(
                            getattr(member_value, "__doc__", "") or ""
                        ).splitlines()
                        signature = (
                            documentation_lines[0]
                            if documentation_lines
                            else ""
                        )
                    ranked.append((
                        relevance_score,
                        {
                            "qualified_name": (
                                f"{module_name}.{class_name}.{member_name}"
                            ),
                            "owner_module": module_name,
                            "import_statement": (
                                f"from {module_name} import {class_name}"
                            ),
                            "signature": signature,
                            "source_excerpt": "",
                            "path": str((spec.origin if spec else "") or ""),
                            "provider": "installed_package_capability_search",
                            "provenance": f"reflection:{module_name}",
                            "confidence": "exact",
                            "authoritative_signature": True,
                            "supports": ", ".join(
                                sorted(class_overlap | member_overlap)
                            ),
                            "relevance_score": relevance_score,
                        },
                    ))
        break
    ranked.sort(
        key=lambda item: (
            -item[0],
            str(item[1]["qualified_name"]).casefold(),
        )
    )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_class_counts: dict[str, int] = {}
    for selection_round in range(1, 7):
        for _score, record in ranked:
            qualified_name = str(record["qualified_name"])
            if qualified_name in seen:
                continue
            qualified_parts = qualified_name.split(".")
            class_key = ".".join(qualified_parts[:3])
            is_bare_class = len(qualified_parts) == 3
            if (
                not is_bare_class
                and per_class_counts.get(class_key, 0) >= selection_round
            ):
                continue
            seen.add(qualified_name)
            if not is_bare_class:
                per_class_counts[class_key] = (
                    per_class_counts.get(class_key, 0) + 1
                )
            deduped.append(record)
            if len(deduped) >= max(1, limit):
                return deduped
    return deduped


def _host_action_capability_queries(text: str) -> list[str]:
    """Turn host behavior clauses into small API-index search queries."""

    source = str(text or "")
    action_pattern = (
        r"\b(create|connect|save|load|export|import|bake|apply|set|update|"
        r"delete|remove|copy|duplicate|rename|assign|attach|detach|inspect|"
        r"list|query|find|get|read|audit|check)\b"
    )
    host_types = list(dict.fromkeys(
        match
        for match in re.findall(r"\bunreal\.([A-Z][A-Za-z0-9_]*)", source)
        if not match.endswith(("Factory", "FactoryNew", "Helpers"))
    ))
    segments: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(source):
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif (
            character in ",;"
            or (
                character == "."
                and index + 1 < len(source)
                and source[index + 1].isspace()
            )
        ) and depth == 0:
            segments.append(source[start:index])
            start = index + 1
    segments.append(source[start:])
    expanded_segments = [
        part.strip()
        for segment in segments
        for part in re.split(
            rf"\s+and\s+(?={action_pattern})",
            segment,
            flags=re.IGNORECASE,
        )
        if part.strip()
    ]
    noise = {
        "a", "an", "and", "created", "current", "from", "new", "of",
        "selected", "the", "those", "to", "using", "value", "values",
        "with",
    }
    queries: list[str] = []

    def add(query: str) -> None:
        normalized = " ".join(str(query or "").split()).strip()
        if normalized and normalized.casefold() not in {
            item.casefold() for item in queries
        }:
            queries.append(normalized)

    for segment in expanded_segments:
        action_match = re.search(action_pattern, segment, flags=re.IGNORECASE)
        if not action_match:
            continue
        action = action_match.group(1).casefold()
        tail = segment[action_match.end():]
        if action == "create" and re.search(
            r"\.py\b|\b(?:class|dialog|inheriting|subclassing)\b",
            tail,
            flags=re.IGNORECASE,
        ):
            continue
        if action == "connect" and re.search(
            r"\.(?:clicked|triggered|toggled|accepted|rejected)\b",
            segment,
            flags=re.IGNORECASE,
        ):
            continue
        tail = re.sub(
            r"\b(?:unreal\.)?[A-Za-z_][A-Za-z0-9_.]*\s*\([^)]*\)",
            " ",
            tail,
        )
        words = [
            word
            for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", tail)
            if word.casefold() not in noise | {"unreal"}
        ]
        if not words:
            continue
        compact_words = words[:5]
        object_words = re.split(
            r"\b(?:for|from|into|to|using|with)\b",
            tail,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        object_tokens = [
            word
            for word in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]*",
                object_words,
            )
            if word.casefold() not in noise
        ]
        object_head = object_tokens[-1] if object_tokens else words[-1]
        if object_head.endswith("s") and len(object_head) > 4:
            object_head = object_head[:-1]
        destination_match = re.search(
            r"\b(?:into|to)\s+(.+)$",
            tail,
            flags=re.IGNORECASE,
        )
        destination_head = ""
        if destination_match:
            destination_tokens = [
                word
                for word in re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]*",
                    destination_match.group(1),
                )
                if word.casefold() not in noise | {"unreal"}
            ]
            if destination_tokens:
                destination_head = destination_tokens[-1]
                if destination_head.endswith("ies") and len(destination_head) > 5:
                    destination_head = destination_head[:-3] + "y"
                elif destination_head.endswith("s") and len(destination_head) > 4:
                    destination_head = destination_head[:-1]
        property_setting = bool(
            action in {"apply", "assign", "set"}
            and len(host_types) >= 2
            and host_types[1].casefold() in tail.casefold()
        )
        if property_setting:
            add(f"set {host_types[0]} {host_types[1]}")
            continue
        if action == "save" and re.search(
            r"\b(?:created|newly\s+created|resulting|returned)\b",
            tail,
            flags=re.IGNORECASE,
        ):
            add(f"save loaded {object_head}")
            continue
        if not (destination_head and host_types):
            add(" ".join([action, *compact_words]))
        if host_types and action in {
            "apply",
            "assign",
            "connect",
            "create",
            "set",
        }:
            add(
                " ".join(
                    [
                        action,
                        host_types[0],
                        object_head,
                        destination_head,
                    ]
                )
            )
        elif not host_types:
            add(f"{action} {object_head} {destination_head}")
    return queries[:12]


def _unreal_records(
    text: str,
    queries: Iterable[str],
    project_root: Path,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        from tech_connector.services.unreal.capability_graph_service import (
            resolve_unreal_graph_item,
            search_unreal_capability_graph,
        )

        exact_queries = [
            query for query in queries if query.startswith("unreal.")
        ][:4]
        host_types = list(dict.fromkeys(
            match
            for match in re.findall(
                r"\bunreal\.([A-Z][A-Za-z0-9_]*)",
                text,
            )
            if not match.endswith(("Factory", "FactoryNew", "Helpers"))
        ))
        priority_queries = set(exact_queries)
        results = [
            resolve_unreal_graph_item(
                query,
                project_root=str(project_root),
                sync=False,
            )
            for query in exact_queries
        ]
        search_result = search_unreal_capability_graph(
            text,
            project_root=str(project_root),
            limit=min(limit, 12),
            sync=False,
        )
        returned_owners = {
            match.group(1)
            for result in results
            for row in result.get("python_api") or []
            if isinstance(row, dict)
            for match in [
                re.search(
                    r"->\s*([A-Za-z_][A-Za-z0-9_]*)",
                    str(
                        row.get("signature")
                        or row.get("python_signature")
                        or ""
                    ),
                )
            ]
            if match
        }
        api_member_terms = list(dict.fromkeys(
            [
                member
                for exact_query in exact_queries
                for member in re.findall(
                    rf"{re.escape(exact_query)}\s*\([^)]*\)"
                    r"\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)",
                    text,
                )
            ]
            + re.findall(
                r"\b([a-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+)\b"
                r"(?=[^.;]{0,50}\b(?:API|signature|factory)\b)",
                text,
                flags=re.IGNORECASE,
            )
        ))
        for returned_owner in sorted(returned_owners)[:2]:
            for member in api_member_terms[:3]:
                chained_query = f"unreal.{returned_owner}.{member}"
                priority_queries.add(chained_query)
                results.append(
                    resolve_unreal_graph_item(
                        chained_query,
                        project_root=str(project_root),
                        sync=False,
                    )
                )
        results.append(search_result)
        for capability_query in _host_action_capability_queries(text):
            capability_result = search_unreal_capability_graph(
                capability_query,
                project_root=str(project_root),
                limit=8,
                sync=False,
            )
            action = capability_query.split(" ", 1)[0].casefold()
            action_markers = {
                "apply": ("apply", "set"),
                "assign": ("assign", "set"),
                "attach": ("attach", "add"),
                "detach": ("detach", "remove"),
            }.get(action, (action,))
            capability_tokens = {
                token.casefold()
                for token in re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]*",
                    capability_query,
                )
                if len(token) > 3
            }
            domain_owner = (
                host_types[0].casefold() if host_types else ""
            )
            ranked_rows: list[tuple[int, dict[str, Any]]] = []
            for row in capability_result.get("python_api") or []:
                if not isinstance(row, dict):
                    continue
                qualified = str(
                    row.get("qualified_name") or ""
                ).casefold()
                qualified_flat = re.sub(r"[^a-z0-9]", "", qualified)
                action_match_count = sum(
                    1 for marker in action_markers if marker in qualified
                )
                exact_domain_owner = bool(
                    domain_owner
                    and f".{domain_owner}." in qualified
                )
                token_match_count = sum(
                    1
                    for token in capability_tokens
                    if token in qualified
                    or re.sub(r"[^a-z0-9]", "", token) in qualified_flat
                )
                property_assignment = bool(
                    action in {"apply", "assign", "set"}
                    and exact_domain_owner
                    and token_match_count >= 2
                )
                if not action_match_count and not property_assignment:
                    continue
                ranked_rows.append((
                    (10 if exact_domain_owner else 0)
                    + action_match_count * 5
                    + token_match_count,
                    row,
                ))
            matching_rows = [
                row
                for _score, row in sorted(
                    ranked_rows,
                    key=lambda item: -item[0],
                )
            ]
            if not matching_rows:
                continue
            capability_result["python_api"] = matching_rows[:1]
            capability_result["capabilities"] = []
            capability_result["functions"] = []
            capability_result["symbols"] = []
            capability_result["_capability_query"] = capability_query
            for row in (capability_result.get("python_api") or [])[:1]:
                if isinstance(row, dict):
                    qualified = str(row.get("qualified_name") or "")
                    if qualified:
                        priority_queries.add(qualified)
            results.append(capability_result)
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    requested_tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text)
    }
    for result in results:
        for key in ("python_api", "capabilities", "functions", "symbols"):
            for row in result.get(key) or []:
                if not isinstance(row, dict):
                    continue
                qualified = str(
                    row.get("qualified_name") or row.get("entrypoint")
                    or row.get("symbol_key") or row.get("name") or ""
                )
                if not qualified:
                    continue
                relevance = sum(
                    1
                    for token in requested_tokens
                    if token in qualified.casefold()
                )
                if key not in {"python_api", "functions"} and relevance <= 0:
                    continue
                signature = str(
                    row.get("signature") or row.get("python_signature")
                    or row.get("schema") or ""
                )
                metadata = row.get("metadata") or {}
                requires_live = bool(
                    row.get("requires_live_unreal")
                    or (
                        isinstance(metadata, dict)
                        and metadata.get("requires_live_unreal")
                    )
                )
                records.append({
                    "qualified_name": qualified,
                    "owner_module": (
                        "unreal" if qualified.startswith("unreal.") else ""
                    ),
                    "import_statement": (
                        "import unreal" if qualified.startswith("unreal.") else ""
                    ),
                    "signature": signature,
                    "source_excerpt": json.dumps(
                        row, ensure_ascii=True, default=str
                    )[:1600],
                    "path": str(row.get("source_path") or ""),
                    "provider": f"unreal_capability_graph:{key}",
                    "provenance": (
                        "offline_unreal_python_api_index"
                        if key == "python_api"
                        else "registered_unreal_capability"
                    ),
                    "confidence": "exact",
                    "authoritative_signature": bool(signature),
                    "execution_requires_live_host": (
                        False if key == "python_api" else requires_live
                    ),
                    "supports": str(
                        result.get("_capability_query") or ""
                    ),
                })
    records.sort(
        key=lambda row: (
            0
            if str(row.get("qualified_name") or "") in priority_queries
            else 1,
            0 if row.get("supports") else 1,
            0 if row.get("authoritative_signature") else 1,
            -sum(
                1
                for token in requested_tokens
                if token in str(row.get("qualified_name") or "").casefold()
            ),
            str(row.get("qualified_name") or "").casefold(),
        )
    )
    return records[:limit]


def _catalog_records(
    hosts: Iterable[str],
    queries: Iterable[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Reuse the existing internal DCC catalog only for host requests."""

    selected_hosts = set(hosts)
    if not selected_hosts:
        return []
    global _DCC_CATALOG_CACHE
    try:
        from tech_connector.services.api_catalog_service import (
            discover_dcc_api_catalog,
        )

        if _DCC_CATALOG_CACHE is None:
            _DCC_CATALOG_CACHE = discover_dcc_api_catalog()
        catalog = _DCC_CATALOG_CACHE
    except Exception:
        return []
    terms = {
        token.lower()
        for query in queries
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", query)
    }
    records: list[dict[str, Any]] = []
    for host in selected_hosts:
        for row in catalog.get("hosts", {}).get(host, []):
            searchable = " ".join(
                [
                    str(row.get("name") or ""),
                    str(row.get("entry_point") or ""),
                    str(row.get("docstring") or ""),
                ]
            ).lower()
            if terms and not any(term in searchable for term in terms):
                continue
            records.append({
                "qualified_name": str(row.get("entry_point") or ""),
                "owner_module": str(row.get("entry_point") or "").rsplit(".", 1)[0],
                "import_statement": "",
                "signature": str(row.get("signature") or ""),
                "source_excerpt": str(row.get("docstring") or "")[:1000],
                "path": str(row.get("file_path") or ""),
                "provider": f"internal_dcc_catalog:{host}",
                "provenance": "existing_internal_api_catalog",
                "confidence": "exact",
                "authoritative_signature": True,
            })
            if len(records) >= limit:
                return records
    return records


def _official_api_records(
    queries: Iterable[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Research explicit unresolved APIs without promoting search results."""

    def official_domains(query: str) -> list[str]:
        lowered = query.casefold()
        if lowered.startswith("unreal."):
            return ["dev.epicgames.com"]
        if lowered.startswith(("maya.", "cmds.", "pyfbsdk.")):
            return ["help.autodesk.com"]
        if lowered.startswith("bpy."):
            return ["docs.blender.org"]
        if lowered.startswith(("pyside", "pyqt", "qt.")):
            return ["doc.qt.io"]
        if lowered.startswith(
            ("pathlib.", "typing.", "json.", "tempfile.", "threading.")
        ):
            return ["docs.python.org"]
        return []

    def verified_signature(
        query: str,
        claims: Iterable[dict[str, Any]],
    ) -> tuple[str, str, str]:
        terminal = query.rsplit(".", 1)[-1]
        pattern = re.compile(
            rf"\b(?:{re.escape(query)}|{re.escape(terminal)})"
            r"\s*\([^()\n]{0,800}\)",
            flags=re.IGNORECASE,
        )
        for claim in claims:
            source_text = " ".join(
                str(claim.get(field) or "")
                for field in ("claim", "supporting_quote")
            )
            match = pattern.search(source_text)
            if match:
                source = dict(claim.get("source") or {})
                return (
                    match.group(0),
                    str(claim.get("supporting_quote") or ""),
                    str(source.get("url") or claim.get("url") or ""),
                )
        return "", "", ""

    records: list[dict[str, Any]] = []
    for query in list(queries)[:2]:
        if query.startswith("unreal."):
            try:
                from tech_connector.bridges.unreal.unreal_api_docs import (
                    lookup_official_unreal_api,
                )

                direct = lookup_official_unreal_api(query, timeout=10.0)
            except Exception:
                direct = None
            if direct:
                direct_signature = str(direct.get("signature") or "")
                records.append({
                    "qualified_name": query,
                    "owner_module": str(
                        direct.get("resolved_owner")
                        or query.rsplit(".", 1)[0]
                    ),
                    "import_statement": "import unreal",
                    "signature": direct_signature,
                    "source_excerpt": str(
                        direct.get("source_excerpt") or ""
                    )[:2200],
                    "path": str(direct.get("source") or ""),
                    "provider": "official_public_api_research",
                    "provenance": str(direct.get("provenance") or ""),
                    "confidence": "exact" if direct_signature else "candidate",
                    "authoritative_signature": bool(direct_signature),
                })
                if len(records) >= limit:
                    break
                continue
        if query not in _OFFICIAL_API_CACHE:
            try:
                from tech_connector.services.knowledge_research_service import (
                    extract_public_source_claims,
                    search_public_sources,
                )

                domains = official_domains(query)
                search_result = search_public_sources(
                    f"{query} Python API exact owner signature arguments",
                    official_only=False,
                    allowed_domains=domains or None,
                    limit=4,
                    timeout=10.0,
                )
                extraction = extract_public_source_claims(
                    list(search_result.get("candidates") or [])[:2],
                    query=f"{query} Python API exact signature",
                    max_sources=2,
                    timeout=10.0,
                )
                _OFFICIAL_API_CACHE[query] = {
                    "ok": bool(extraction.get("claims")),
                    "official_domains": domains,
                    "search": search_result,
                    "claims": list(extraction.get("claims") or []),
                }
            except Exception as exc:
                _OFFICIAL_API_CACHE[query] = {
                    "ok": False,
                    "error": str(exc),
                }
        cached = _OFFICIAL_API_CACHE[query]
        if not cached.get("ok"):
            continue
        signature, supporting_quote, source_url = verified_signature(
            query,
            cached.get("claims") or [],
        )
        records.append({
            "qualified_name": query,
            "owner_module": query.rsplit(".", 1)[0],
            "import_statement": "",
            "signature": signature,
            "source_excerpt": supporting_quote[:2200],
            "path": source_url,
            "provider": (
                "official_public_api_research"
                if signature and cached.get("official_domains")
                else "public_api_research_candidate"
            ),
            "provenance": (
                "official_document_exact_signature"
                if signature and cached.get("official_domains")
                else "public_source_verified_claim"
            ),
            "confidence": "exact" if signature else "candidate",
            "authoritative_signature": bool(
                signature and cached.get("official_domains")
            ),
        })
        if len(records) >= limit:
            break
    return records


def build_symbol_evidence_packet(
    text: str,
    *,
    project_root: str | Path,
    generated_overlay: Iterable[tuple[str, str, str]] | None = None,
    host: str | None = None,
    limit: int = 12,
    allow_official_research: bool = False,
    capability_search: bool = True,
) -> dict[str, Any]:
    """Compose existing symbol providers for generation and focused repair."""

    evidence_started = time.perf_counter()
    root = Path(project_root).expanduser().resolve()
    hosts = list(detect_symbol_evidence_hosts(text))
    explicit_host = str(host or "").strip().lower()
    if explicit_host and explicit_host not in hosts:
        hosts.append(explicit_host)
    queries = extract_symbol_evidence_queries(
        text,
        limit=max(limit * 2, 32),
    )
    overlay = list(generated_overlay or [])
    catalog_hosts = [
        selected_host
        for selected_host in hosts
        if not (
            selected_host == "unreal"
            and any(query.startswith("unreal.") for query in queries)
        )
    ]
    multi_dcc = len(hosts) > 1
    cache_key = _evidence_packet_cache_key(
        text,
        root=root,
        overlay=overlay,
        host=host,
        limit=limit,
        allow_official_research=allow_official_research,
        capability_search=capability_search,
    )
    cached_packet = _cached_evidence_packet(cache_key)
    if cached_packet is not None:
        # Unindexed temporary roots intentionally share tools evidence. Keep
        # caller-facing location metadata accurate when reusing that packet.
        cached_packet["project_root"] = str(root)
        cached_packet["index_path"] = str(
            Path(project_index_db_path(root))
            if Path(project_index_db_path(root)).exists()
            else Path(project_index_db_path(TOOLS_ROOT))
        )
        cached_packet["cache_hit"] = True
        cached_packet["evidence_total_ms"] = round(
            (time.perf_counter() - evidence_started) * 1000.0,
            3,
        )
        return cached_packet

    providers: list[
        tuple[str, Callable[[], list[dict[str, Any]]]]
    ] = [
        (
            "generated_overlay",
            lambda: _overlay_records(queries, overlay, root),
        ),
        (
            "capability_catalog",
            lambda: (
                _capability_catalog_records(
                    text,
                    project_root=root,
                    limit=limit,
                )
                if capability_search
                else []
            ),
        ),
        (
            "host_adapter_capabilities",
            lambda: _host_adapter_capability_records(
                text,
                hosts=hosts,
                project_root=root,
                limit=max(12, limit),
            ),
        ),
        (
            "project_index",
            lambda: _intelligence_records(text, root, limit=limit),
        ),
        (
            "tools_index",
            lambda: (
                _intelligence_records(text, TOOLS_ROOT, limit=limit)
                if root != TOOLS_ROOT
                else []
            ),
        ),
        (
            "installed_packages",
            lambda: _installed_records(queries, limit=limit),
        ),
        (
            "installed_qt",
            lambda: (
                _installed_qt_capability_records(
                    text,
                    limit=max(16, limit * 2),
                )
                if capability_search
                else []
            ),
        ),
        (
            "unreal_index",
            lambda: (
                _unreal_records(text, queries, root, limit=limit)
                if "unreal" in hosts
                else []
            ),
        ),
        (
            "host_adapter_index",
            lambda: [
                record
                for host in sorted(hosts)
                for record in _intelligence_records(
                    (
                        f"{host.title()}Adapter internal adapter bridge "
                        + " ".join(queries[:8])
                    ),
                    root,
                    limit=max(12, limit),
                )
            ],
        ),
        (
            "dcc_catalog",
            lambda: _catalog_records(catalog_hosts, queries, limit=limit),
        ),
        (
            "multi_dcc_bridge",
            lambda: (
                _intelligence_records(
                    "ProjectIntelligenceService host bridge DCC adapter "
                    "execute_unreal_capability Maya bridge",
                    root,
                    limit=8,
                )
                if multi_dcc
                else []
            ),
        ),
    ]
    records: list[dict[str, Any]] = []
    provider_errors: list[dict[str, str]] = []
    provider_timings: list[dict[str, Any]] = []
    lookup_decisions: list[dict[str, Any]] = []

    def run_provider_batch(
        selected_providers: list[
            tuple[str, Callable[[], list[dict[str, Any]]]]
        ],
        *,
        phase: str,
    ) -> None:
        if not selected_providers:
            return

        def timed_provider(
            provider_name: str,
            provider: Callable[[], list[dict[str, Any]]],
        ) -> tuple[list[dict[str, Any]], float]:
            started = time.perf_counter()
            values = list(provider() or [])
            return values, (time.perf_counter() - started) * 1000.0

        with ThreadPoolExecutor(
            max_workers=min(6, len(selected_providers)),
            thread_name_prefix=f"symbol-evidence-{phase}",
        ) as executor:
            futures = [
                (
                    provider_name,
                    executor.submit(
                        timed_provider,
                        provider_name,
                        provider,
                    ),
                )
                for provider_name, provider in selected_providers
            ]
            for provider_name, future in futures:
                try:
                    values, elapsed_ms = future.result()
                    records.extend(values)
                    provider_timings.append({
                        "provider": provider_name,
                        "phase": phase,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "record_count": len(values),
                        "status": "complete",
                    })
                except Exception as exc:
                    provider_errors.append({
                        "provider": provider_name,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    provider_timings.append({
                        "provider": provider_name,
                        "phase": phase,
                        "elapsed_ms": 0.0,
                        "record_count": 0,
                        "status": "failed",
                    })

    reflection_provider_names = {"installed_packages", "installed_qt"}
    fast_provider_names = {
        "generated_overlay",
        "host_adapter_capabilities",
        "project_index",
        "unreal_index",
    }
    fast_prepared_providers = [
        item for item in providers if item[0] in fast_provider_names
    ]
    deferred_prepared_providers = [
        item
        for item in providers
        if item[0] not in reflection_provider_names | fast_provider_names
    ]
    reflection_providers = [
        item for item in providers if item[0] in reflection_provider_names
    ]
    run_provider_batch(fast_prepared_providers, phase="prepared_exact")
    host_adapter_covered = any(
        record.get("provider") == "host_adapter_capability_index"
        and record.get("authoritative_signature")
        and record.get("supports")
        for record in records
    )
    internal_host_request = bool(
        hosts
        and re.search(
            r"\b(?:existing|internal|adapter|bridge)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    skip_broad_discovery = bool(
        host_adapter_covered
        and internal_host_request
        and not multi_dcc
    )
    lookup_decisions.append({
        "decision": "broad_capability_discovery",
        "executed": not skip_broad_discovery,
        "reason": (
            "exact authoritative host-adapter members cover the internal host request"
            if skip_broad_discovery
            else "exact prepared evidence did not fully cover the request"
        ),
    })
    if skip_broad_discovery:
        provider_timings.extend({
            "provider": provider_name,
            "phase": "prepared_broad",
            "elapsed_ms": 0.0,
            "record_count": 0,
            "status": "skipped",
        } for provider_name, _provider in deferred_prepared_providers)
    else:
        run_provider_batch(
            deferred_prepared_providers,
            phase="prepared_broad",
        )

    prepared_names = {
        str(record.get("qualified_name") or "").casefold()
        for record in records
        if record.get("authoritative_signature")
    }
    unresolved_prepared_queries = [
        query
        for query in queries
        if not any(
            candidate == query.casefold()
            or candidate.endswith("." + query.casefold())
            or query.casefold().endswith("." + candidate)
            for candidate in prepared_names
        )
    ]
    requires_runtime_reflection = bool(
        unresolved_prepared_queries
        and (
            any(
                (
                    "." in query
                    or query.startswith(("PySide", "PyQt", "Q"))
                )
                for query in unresolved_prepared_queries
            )
            or bool(re.search(
                r"\b(?:Qt|PySide[26]?|PyQt[56]?)\b",
                text,
                flags=re.IGNORECASE,
            ))
            or not records
        )
    )
    lookup_decisions.append({
        "decision": "runtime_reflection",
        "executed": requires_runtime_reflection,
        "reason": (
            "prepared evidence did not cover installed-package or Qt symbols"
            if requires_runtime_reflection
            else "prepared indexed evidence covered the requested surface"
        ),
        "unresolved_queries": unresolved_prepared_queries,
    })
    if requires_runtime_reflection:
        run_provider_batch(reflection_providers, phase="runtime_fallback")
    else:
        provider_timings.extend({
            "provider": provider_name,
            "phase": "runtime_fallback",
            "elapsed_ms": 0.0,
            "record_count": 0,
            "status": "skipped",
        } for provider_name, _ in reflection_providers)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (
            str(record.get("qualified_name") or ""),
            str(record.get("provider") or ""),
            str(record.get("path") or ""),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(record)

    deduped.sort(
        key=lambda row: (
            0 if row.get("supports") else 1,
            -int(row.get("relevance_score") or 0),
            0
            if row.get("authoritative_signature")
            else 1
            if row.get("provider") == "official_public_api_research"
            else 2
            if str(row.get("confidence") or "") == "exact"
            else 3,
            str(row.get("qualified_name") or "").casefold(),
            str(row.get("path") or "").casefold(),
        )
    )

    proven = {
        str(row.get("qualified_name") or "").lower()
        for row in deduped
        if row.get("authoritative_signature")
    }
    def is_prohibited_host_reference(query: str) -> bool:
        """Return whether a host API mention is explicitly forbidden by the request."""

        return bool(re.search(
            r"\b(?:rather\s+than|instead\s+of|without|do\s+not|don't|"
            r"must\s+not|never|avoid)\s+"
            r"(?:directly\s+)?(?:importing|import|using|use)\s+"
            rf"[^.;\n]{{0,160}}\b{re.escape(query)}\b",
            text,
            flags=re.IGNORECASE,
        ))

    explicit_host_queries = [
        query for query in queries
        if any(
            query == module or query.startswith(module + ".")
            for selected_host in hosts
            for module in _HOST_MODULES.get(selected_host, ())
        )
        and not is_prohibited_host_reference(query)
    ]
    unresolved = [
        query for query in explicit_host_queries
        if not any(
            candidate == query.lower()
            or candidate.startswith(query.lower() + ".")
            or query.lower().startswith(candidate + ".")
            for candidate in proven
        )
    ]
    explicit_chained_members = list(dict.fromkeys(
        (
            f"{owner}().{member}",
            member,
        )
        for owner, member in re.findall(
            r"\b((?:unreal|maya\.cmds|maya\.api\.OpenMaya|maya\.OpenMaya|"
            r"cmds|bpy|pyfbsdk)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
            r"\s*\([^)]*\)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)",
            text,
        )
    ))
    unresolved.extend(
        chain
        for chain, member in explicit_chained_members
        if not any(
            candidate.endswith("." + member.casefold())
            for candidate in proven
        )
    )
    if allow_official_research and unresolved:
        official_records = _official_api_records(unresolved, limit=4)
        for record in official_records:
            key = (
                str(record.get("qualified_name") or ""),
                str(record.get("provider") or ""),
                str(record.get("path") or ""),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(record)
        officially_resolved = {
            str(record.get("qualified_name") or "")
            for record in official_records
        }
        unresolved = [
            query for query in unresolved if query not in officially_resolved
        ]
    capability_intents: list[dict[str, Any]] = []
    gap_resolution: dict[str, Any] = {
        "evidence": [],
        "unresolved_intents": [],
        "acquisition_requests": [],
        "provider_errors": [],
        "local_resolution_complete": True,
        "online_search_performed": False,
    }
    try:
        from tech_connector.services.capability_resolution_service import (
            resolve_capabilities,
        )
        capability_resolution = resolve_capabilities(
            text,
            limit=max(24, limit * 2),
        )
        capability_intents = list(
            capability_resolution.get("intents") or []
        )
        from tech_connector.services.capability_gap_resolution_service import (
            resolve_unnamed_capability_gaps,
        )
        gap_resolution = resolve_unnamed_capability_gaps(
            capability_intents,
            deduped,
            project_root=root,
            allow_online=allow_official_research,
            local_provider_errors=provider_errors,
        )
    except Exception as exc:
        provider_errors.append({
            "provider": "capability_gap_resolution",
            "error": f"{type(exc).__name__}: {exc}",
        })

    for record in gap_resolution.get("evidence") or []:
        key = (
            str(record.get("qualified_name") or ""),
            str(record.get("provider") or ""),
            str(record.get("path") or ""),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(dict(record))
    provider_errors.extend(
        dict(item)
        for item in gap_resolution.get("provider_errors") or []
        if isinstance(item, dict)
    )
    newly_proven = {
        str(row.get("qualified_name") or "").casefold()
        for row in deduped
        if row.get("authoritative_signature")
    }
    unresolved = [
        query
        for query in unresolved
        if not any(
            candidate == query.casefold()
            or candidate.startswith(query.casefold() + ".")
            or query.casefold().startswith(candidate + ".")
            for candidate in newly_proven
        )
    ]
    packet = {
        "schema": "tech_connector.symbol_evidence.v2",
        "project_root": str(root),
        "index_path": str(
            Path(project_index_db_path(root))
            if Path(project_index_db_path(root)).exists()
            else Path(project_index_db_path(TOOLS_ROOT))
        ),
        "snapshot_id": cache_key,
        "queries": queries,
        "capability_intents": capability_intents,
        "hosts": hosts,
        "multi_dcc": multi_dcc,
        "provider_errors": provider_errors,
        "architecture": (
            "bridge_or_adapter_coordinator_with_host_local_leaf_modules"
            if multi_dcc else "host_local_or_project_module"
        ),
        "evidence": deduped[: max(16, limit * 4)],
        "unresolved_host_api_queries": unresolved,
        "unresolved_capability_intents": list(
            gap_resolution.get("unresolved_intents") or []
        ),
        "capability_acquisition_requests": list(
            gap_resolution.get("acquisition_requests") or []
        ),
        "capability_resolution_status": str(
            gap_resolution.get("status") or ""
        ),
        "local_capability_resolution_complete": bool(
            gap_resolution.get("local_resolution_complete", True)
        ),
        "online_capability_search_performed": bool(
            gap_resolution.get("online_search_performed", False)
        ),
        "cache_hit": False,
        "provider_timings": provider_timings,
        "lookup_decisions": lookup_decisions,
        "evidence_total_ms": round(
            (time.perf_counter() - evidence_started) * 1000.0,
            3,
        ),
    }
    return _store_evidence_packet(cache_key, packet)


def resolve_runtime_api_evidence(
    api_path: str,
    *,
    project_root: str | Path,
    allow_official_research: bool = False,
) -> bool | None:
    """Return True only for exact indexed, installed, host, or official evidence."""

    cached_official = _OFFICIAL_API_CACHE.get(str(api_path or "").strip())
    if cached_official and cached_official.get("ok"):
        return True
    target_path = str(api_path or "").strip()
    if allow_official_research and target_path.startswith("unreal."):
        try:
            from tech_connector.bridges.unreal.unreal_api_docs import (
                lookup_official_unreal_api,
            )

            if lookup_official_unreal_api(target_path, timeout=10.0):
                return True
        except Exception:
            pass
    packet = build_symbol_evidence_packet(
        api_path,
        project_root=project_root,
        allow_official_research=allow_official_research,
        limit=8,
    )
    target = str(api_path or "").strip().lower()
    for row in packet.get("evidence") or []:
        qualified = str(row.get("qualified_name") or "").strip().lower()
        if qualified != target:
            continue
        if (
            row.get("provider") == "official_public_api_research"
            and row.get("authoritative_signature")
            and row.get("signature")
        ):
            return True
        if row.get("confidence") == "exact" and (
            row.get("authoritative_signature")
            or str(row.get("provider") or "").startswith(
                ("unreal_capability_graph:", "installed_package_inspection")
            )
        ):
            return True
    return None


def resolve_runtime_api_record(
    api_path: str,
    *,
    project_root: str | Path,
    allow_official_research: bool = False,
    allow_unique_owner_suffix: bool = False,
) -> dict[str, Any] | None:
    """Resolve an API path to its authoritative canonical evidence record.

    :param api_path: Proposed qualified callable or property path.
    :param project_root: Active project used for project and shared-index lookup.
    :param allow_official_research: Whether official online evidence may be used.
    :param allow_unique_owner_suffix: Whether one unique ``Owner.member`` match
        may canonicalize an otherwise incorrect module prefix.
    :return: The verified canonical evidence record, or ``None``.
    """

    target = str(api_path or "").strip().casefold()
    if not target:
        return None
    packet = build_symbol_evidence_packet(
        api_path,
        project_root=project_root,
        allow_official_research=allow_official_research,
        limit=16,
    )

    def is_authoritative(row: Mapping[str, Any]) -> bool:
        provider = str(row.get("provider") or "")
        return bool(
            row.get("authoritative_signature")
            and row.get("signature")
            and (
                row.get("confidence") == "exact"
                or provider == "official_public_api_research"
                or provider.startswith("unreal_capability_graph:")
                or provider == "installed_package_inspection"
            )
        )

    authoritative_rows = [
        dict(row)
        for row in packet.get("evidence") or []
        if isinstance(row, Mapping) and is_authoritative(row)
    ]
    for row in authoritative_rows:
        if str(row.get("qualified_name") or "").strip().casefold() == target:
            return row
    if not allow_unique_owner_suffix:
        return None
    target_parts = [part for part in target.split(".") if part]
    if len(target_parts) < 2:
        return None
    owner_suffix = ".".join(target_parts[-2:])
    suffix_matches = {
        str(row.get("qualified_name") or "").strip(): row
        for row in authoritative_rows
        if str(row.get("qualified_name") or "")
        .strip()
        .casefold()
        .endswith("." + owner_suffix)
    }
    if len(suffix_matches) == 1:
        return next(iter(suffix_matches.values()))
    return None


def render_symbol_evidence_packet(
    packet: dict[str, Any], *, max_chars: int = 12000
) -> str:
    """Render verified candidates and mandatory provenance rules for workers."""

    if not packet:
        return ""
    lines = [
        "VERIFIED FEDERATED SYMBOL EVIDENCE:",
        f"- project_root: {packet.get('project_root') or ''}",
        f"- hosts: {', '.join(packet.get('hosts') or []) or 'none'}",
        f"- architecture: {packet.get('architecture') or ''}",
    ]
    for row in packet.get("evidence") or []:
        lines.append(
            f"- {row.get('qualified_name')} [{row.get('provider')}; "
            f"confidence={row.get('confidence')}; provenance={row.get('provenance')}]"
        )
        if row.get("import_statement"):
            lines.append(f"  import: {row['import_statement']}")
        if row.get("signature"):
            lines.append(f"  signature: {row['signature']}")
        if row.get("access_kind"):
            lines.append(f"  usage: {row['access_kind']}")
        if row.get("path"):
            lines.append(f"  source: {row['path']}")
        if "execution_requires_live_host" in row:
            lines.append(
                "  execution_requires_live_host: "
                + str(bool(row["execution_requires_live_host"]))
            )
        if row.get("source_excerpt"):
            lines.append(
                "  evidence: "
                + " ".join(str(row["source_excerpt"]).split())[:650]
            )
    unresolved = list(packet.get("unresolved_host_api_queries") or [])
    if unresolved:
        lines.append("- unresolved_host_api_queries: " + ", ".join(unresolved))
    lines.extend([
        "MANDATORY EVIDENCE RULES:",
        "- Prefer exact generated/project owners before creating duplicates.",
        "- Do not invent imports, owners, methods, factories, enums, or signatures.",
        "- Usage-proven evidence proves existence, not undocumented arguments.",
        "- Unresolved host APIs require bridge/reflection or official evidence.",
    ])
    if packet.get("multi_dcc"):
        lines.extend([
            "- This is a multi-DCC request. Coordinator modules must use indexed "
            "bridges/adapters and must not directly execute multiple host SDKs.",
            "- Direct Unreal, Maya, Blender, or MotionBuilder SDK calls are allowed "
            "only inside the corresponding host-local leaf adapter.",
            "- Bridge execution must preflight reachability. If a required host is "
            "unreachable, propagate the structured unavailable result so the "
            "application can call its existing missing-DCC launch prompt and retry "
            "the pending bridge operation after the user approves and the host connects.",
        ])
    else:
        lines.append(
            "- A host-local leaf may use its native API directly when the evidence "
            "above proves the call; do not replace a valid base API with a bridge."
        )
    return "\n".join(lines)[:max_chars]
