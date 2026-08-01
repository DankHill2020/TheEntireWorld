"""Federated, typed capability discovery for planning and code generation.

This module converts request clauses into contextual capability intents before
consulting the existing registries. Broad verbs such as ``import`` and
``create`` are never submitted as standalone queries; they remain attached to
their host, object, explicit owner, and surrounding constraints.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable


_ACTION_ALIASES = {
    "bake": "bake",
    "build": "build",
    "connect": "connect",
    "convert": "convert",
    "copy": "copy",
    "create": "create",
    "delete": "delete",
    "execute": "execute",
    "export": "export",
    "extract": "extract",
    "find": "find",
    "generate": "generate",
    "get": "get",
    "import": "import",
    "load": "load",
    "normalize": "normalize",
    "open": "open",
    "output": "export",
    "process": "process",
    "query": "query",
    "read": "read",
    "retarget": "retarget",
    "save": "save",
    "select": "select",
    "set": "set",
    "sync": "sync",
    "track": "track",
    "update": "update",
    "validate": "validate",
    "write": "write",
}
_HOST_PATTERNS = {
    "maya": re.compile(r"\b(?:maya|maya\.cmds|pymel)\b", re.IGNORECASE),
    "unreal": re.compile(r"\b(?:unreal|ue[45])\b", re.IGNORECASE),
    "blender": re.compile(r"\b(?:blender|bpy)\b", re.IGNORECASE),
    "motionbuilder": re.compile(
        r"\b(?:motionbuilder|motion builder|pyfbsdk)\b",
        re.IGNORECASE,
    ),
    "qt": re.compile(
        r"\b(?:qt|pyside[26]?|pyqt[56]?|qthread|qrunnable|qthreadpool)\b",
        re.IGNORECASE,
    ),
}
_NON_OBJECT_TERMS = {
    "a", "all", "an", "and", "api", "as", "at", "be", "both", "by",
    "call", "class", "code", "current", "do", "each", "existing", "file",
    "for", "from", "function", "in", "internal", "into", "is", "it",
    "method", "module", "must", "of", "on", "or", "project", "requested",
    "our", "onto", "python", "should", "take", "that", "the", "their",
    "then", "this", "through", "to",
    "use", "using", "via", "when", "which", "with", "without",
    "like", "need", "please", "want", "would", "you",
    *_ACTION_ALIASES,
    *_HOST_PATTERNS,
}
_OWNER_SUFFIXES = (
    "Adapter",
    "Bridge",
    "Client",
    "Dialog",
    "Factory",
    "Generator",
    "Manager",
    "Service",
    "Subsystem",
    "Transport",
    "Widget",
    "Worker",
)


@dataclass(frozen=True)
class CapabilityIntent:
    """Represent one contextual operation requested by the user.

    :param action: Canonical operation verb, such as ``export`` or ``save``.
    :param object_terms: Specific nouns that distinguish the operation target.
    :param hosts: DCC, UI toolkit, or runtime domains attached to the operation.
    :param explicit_symbols: Exact dotted symbols or named dependency owners.
    :param constraints: Nearby behavioral constraints retained for ranking.
    :param source_clause: Original clause from which the intent was extracted.
    :param query: Contextual catalog query; never a standalone broad verb.
    """

    action: str
    object_terms: tuple[str, ...]
    hosts: tuple[str, ...]
    explicit_symbols: tuple[str, ...]
    constraints: tuple[str, ...]
    source_clause: str
    query: str


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _complete_callable_signature(value: Any) -> bool:
    """Return whether indexed callable evidence contains a complete signature."""

    signature = " ".join(str(value or "").split())
    if signature.startswith("def "):
        signature = signature[4:]
    opening = signature.find("(")
    if opening <= 0:
        return False
    depth = 0
    closing = -1
    for index, character in enumerate(signature[opening:], start=opening):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                closing = index
                break
        if depth < 0:
            return False
    if closing < 0 or depth != 0:
        return False
    suffix = signature[closing + 1:].strip().rstrip(":").strip()
    return not suffix or suffix.startswith("->")


def _hosts(text: str) -> tuple[str, ...]:
    return tuple(
        host for host, pattern in _HOST_PATTERNS.items() if pattern.search(text)
    )


def _explicit_symbols(text: str) -> tuple[str, ...]:
    dotted = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*"
        r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b",
        text,
    )
    owners = re.findall(
        rf"\b[A-Z][A-Za-z0-9_]*(?:{'|'.join(_OWNER_SUFFIXES)})\b",
        text,
    )
    return _ordered_unique([*dotted, *owners])


def _object_terms(clause: str, action: str) -> tuple[str, ...]:
    word_matches = list(re.finditer(r"[A-Za-z][A-Za-z0-9_]{2,}", clause))
    action_positions = [
        match.start()
        for match in word_matches
        if (
            match.group(0).casefold() == action
            or (
                len(action) >= 4
                and match.group(0).casefold().startswith(action[:4])
            )
        )
    ]
    action_position = action_positions[0] if action_positions else len(clause) // 2
    ranked: list[tuple[int, int, str]] = []
    for source_index, match in enumerate(word_matches):
        word = match.group(0)
        lowered = word.casefold()
        if lowered in _NON_OBJECT_TERMS or lowered == action:
            continue
        if any(pattern.fullmatch(word) for pattern in _HOST_PATTERNS.values()):
            continue
        ranked.append((abs(match.start() - action_position), source_index, word))
    return _ordered_unique(
        word for _distance, _source_index, word in sorted(ranked)
    )[:10]


def extract_capability_intents(text: str) -> list[CapabilityIntent]:
    """Extract contextual capability operations from arbitrary request prose.

    :param text: User request, requirement batch, or focused repair description.
    :return: Ordered, deduplicated typed capability intents.
    """

    source = " ".join(str(text or "").split())
    if not source:
        return []
    global_hosts = _hosts(source)
    clauses = [
        value.strip()
        for value in re.split(r"(?<=[.!?;])\s+|\n+", source)
        if value.strip()
    ]
    intents: list[CapabilityIntent] = []
    seen: set[tuple[Any, ...]] = set()
    for clause in clauses:
        actions = _ordered_unique(
            _ACTION_ALIASES[match.group(1).casefold()]
            for match in re.finditer(
                rf"\b({'|'.join(_ACTION_ALIASES)})"
                r"(?:s|ed|ing)?\b",
                clause,
                flags=re.IGNORECASE,
            )
        )
        if re.search(
            r"\b(?:take|read|load|consume|receive|from)\b.+?"
            r"\b(?:output|produce|emit|write|into|to)\b",
            clause,
            flags=re.IGNORECASE,
        ):
            actions = _ordered_unique([*actions, "convert"])
        symbols = _explicit_symbols(clause)
        clause_hosts = _hosts(clause) or global_hosts
        for action in actions:
            objects = _object_terms(clause, action)
            # A broad operation without an object, host, or exact symbol is not
            # sufficiently grounded to query a capability catalog.
            if not objects and not clause_hosts and not symbols:
                continue
            constraints = _ordered_unique(
                marker
                for marker, pattern in (
                    ("background", r"\b(?:background|off the UI thread|non-blocking)\b"),
                    ("internal_only", r"\b(?:internal|existing|project)\b"),
                    ("no_direct_host_api", r"\b(?:instead of|rather than|without)\s+import"),
                    ("progress", r"\bprogress(?:_callback)?\b"),
                    ("testable", r"\b(?:test|verify|prove|observable)\b"),
                )
                if re.search(pattern, clause, flags=re.IGNORECASE)
            )
            query_parts = [
                *clause_hosts,
                action,
                *objects,
                *symbols,
            ]
            query = " ".join(_ordered_unique(query_parts))
            key = (action, objects, clause_hosts, symbols, constraints)
            if key in seen:
                continue
            seen.add(key)
            intents.append(CapabilityIntent(
                action=action,
                object_terms=objects,
                hosts=clause_hosts,
                explicit_symbols=symbols,
                constraints=constraints,
                source_clause=clause,
                query=query,
            ))
    return intents


@lru_cache(maxsize=1)
def _general_registry() -> Any:
    from tech_connector.services.capability_registry import CapabilityRegistry

    package_root = Path(__file__).resolve().parents[1]
    registry_path = package_root / "data" / "capability_registry.json"
    return CapabilityRegistry(registry_path)


def _host_app(host: str) -> str | None:
    return {
        "maya": "Maya",
        "unreal": "Unreal",
        "blender": "Blender",
        "motionbuilder": "MotionBuilder",
    }.get(host)


def _indexed_capability_candidates(
    intents: list[CapabilityIntent],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return exact callable definitions from persistent internal indexes.

    Catalog entries are useful for broad discovery, but an indexed callable
    definition is the authority for an internal signature. Search by each
    owned operation rather than by one concatenated prompt so composable
    pipeline stages are not displaced by broad-query ranking.

    :param intents: Typed capability operations extracted from the request.
    :param limit: Maximum exact definitions retained across all operations.
    :return: Ranked authoritative callable evidence records.
    """

    package_root = Path(__file__).resolve().parents[1]
    tools_root = package_root.parent
    index_paths = list(dict.fromkeys([
        tools_root / "knowledge" / "index" / "knowledge_index_v2.sqlite",
        package_root / "knowledge" / "index" / "knowledge_index_v2.sqlite",
    ]))
    ranked: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}

    for index_path in index_paths:
        if not index_path.is_file():
            continue
        try:
            connection = sqlite3.connect(str(index_path))
            connection.row_factory = sqlite3.Row
            for intent_index, intent in enumerate(intents):
                action = intent.action.casefold()
                ranked_rows: list[tuple[sqlite3.Row, int]] = []
                for object_term in intent.object_terms:
                    normalized_object = re.sub(
                        r"[^a-z0-9_]+",
                        "_",
                        object_term.casefold(),
                    ).strip("_")
                    if len(normalized_object) < 3:
                        continue
                    for compound_query in (
                        f"{action}_{normalized_object}*",
                        f"{normalized_object}_{action}*",
                    ):
                        ranked_rows.extend(
                            (row, 24)
                            for row in connection.execute(
                                """
                                SELECT name, qualname, signature, path, docstring
                                FROM symbols_fts
                                WHERE symbols_fts MATCH ?
                                LIMIT 32
                                """,
                                (compound_query,),
                            ).fetchall()
                        )
                ranked_rows.extend(
                    (row, 0)
                    for row in connection.execute(
                    """
                    SELECT name, qualname, signature, path, docstring
                    FROM symbols_fts
                    WHERE symbols_fts MATCH ?
                    LIMIT 96
                    """,
                    (f"{action}*",),
                    ).fetchall()
                )
                object_terms = {
                    value.casefold() for value in intent.object_terms
                }
                host_terms = {value.casefold() for value in intent.hosts}
                explicit_symbols = {
                    value.casefold() for value in intent.explicit_symbols
                }
                for row, query_bonus in ranked_rows:
                    signature = str(row["signature"] or "").strip()
                    qualname = str(row["qualname"] or row["name"] or "").strip()
                    source_path = str(row["path"] or "").strip()
                    if (
                        not _complete_callable_signature(signature)
                        or not qualname
                        or not source_path
                    ):
                        continue
                    leaf = qualname.rsplit(".", 1)[-1]
                    if leaf.startswith("_") and qualname.casefold() not in explicit_symbols:
                        continue
                    haystack = " ".join(
                        str(row[key] or "")
                        for key in ("name", "qualname", "signature", "path", "docstring")
                    ).casefold()
                    object_overlap = {
                        value for value in object_terms if value in haystack
                    }
                    host_overlap = {
                        value for value in host_terms if value in haystack
                    }
                    explicit_overlap = {
                        value for value in explicit_symbols if value in haystack
                    }
                    action_in_name = action in str(row["name"] or "").casefold()
                    if not (
                        explicit_overlap
                        or action_in_name
                        or (action in haystack and object_overlap)
                    ):
                        continue
                    score = (
                        query_bonus
                        +
                        (12 if explicit_overlap else 0)
                        + (8 if action_in_name else 3)
                        + (3 * len(object_overlap))
                        + (2 * len(host_overlap))
                    )
                    try:
                        relative = Path(source_path).resolve().relative_to(tools_root)
                        module = ".".join(relative.with_suffix("").parts)
                        qualified_name = f"{module}.{qualname}"
                    except (OSError, ValueError):
                        qualified_name = qualname
                    key = (qualified_name.casefold(), source_path.casefold())
                    existing = ranked.get(key)
                    if existing is None:
                        record = {
                            "qualified_name": qualified_name,
                            "signature": signature,
                            "path": source_path,
                            "source_excerpt": str(row["docstring"] or "")[:1600],
                            "kind": "internal_function",
                            "provider": "persistent_symbol_index",
                            "provenance": f"knowledge_index_v2:{index_path}",
                            "confidence": "exact",
                            "authoritative_signature": True,
                            "supports": [intent.source_clause],
                            "query_links": [intent.query],
                            "capability_relationships": {"requires": []},
                            "intent_indexes": [intent_index],
                            "_capability_score": score,
                        }
                        ranked[key] = (score, record)
                    else:
                        existing_score, record = existing
                        record["supports"] = list(dict.fromkeys([
                            *record["supports"],
                            intent.source_clause,
                        ]))
                        record["query_links"] = list(dict.fromkeys([
                            *record["query_links"],
                            intent.query,
                        ]))
                        record["intent_indexes"] = sorted(set([
                            *record["intent_indexes"],
                            intent_index,
                        ]))
                        record["_capability_score"] = max(
                            int(record.get("_capability_score") or 0),
                            score,
                        )
                        ranked[key] = (max(existing_score, score), record)
        except (sqlite3.Error, OSError):
            continue
        finally:
            if "connection" in locals():
                connection.close()

    ordered = sorted(
        ranked.values(),
        key=lambda item: (
            -item[0],
            item[1]["qualified_name"].casefold(),
        ),
    )
    return [record for _score, record in ordered[: max(1, int(limit))]]


def resolve_capabilities(text: str, *, limit: int = 32) -> dict[str, Any]:
    """Resolve typed request intents through the existing capability catalogs.

    :param text: Request or owned requirement batch.
    :param limit: Maximum normalized candidates returned.
    :return: Intent rows, ranked candidates, and ambiguity metadata.
    """

    intents = extract_capability_intents(text)
    records: dict[tuple[str, str], dict[str, Any]] = {}

    try:
        from tech_connector.project_analysis.capability_registry import (
            find_capabilities,
        )
    except Exception:
        find_capabilities = None

    batched_project_matches: dict[str | None, list[dict[str, Any]]] = {}
    if find_capabilities is not None and intents:
        requested_apps = list(dict.fromkeys(
            app
            for intent in intents
            for app in (
                [
                    value
                    for value in (
                        _host_app(host) for host in intent.hosts
                    )
                    if value
                ]
                or [None]
            )
        ))
        batched_query = " ".join(dict.fromkeys(
            token
            for intent in intents
            for token in intent.query.split()
            if token
        ))
        for app in requested_apps:
            try:
                batched_project_matches[app] = find_capabilities(
                    batched_query,
                    app=app,
                    max_results=max(64, min(limit * 6, 256)),
                )
            except Exception:
                batched_project_matches[app] = []

    def matches_intent(
        match: dict[str, Any],
        intent: CapabilityIntent,
    ) -> bool:
        haystack = " ".join(
            str(match.get(field) or "")
            for field in (
                "name", "signature", "docstring", "tags",
                "operation_keys", "local_calls", "unreal_calls",
            )
        ).casefold()
        explicit = [
            value.casefold() for value in intent.explicit_symbols
        ]
        if explicit and any(value in haystack for value in explicit):
            return True
        action_match = bool(
            intent.action and intent.action.casefold() in haystack
        )
        object_matches = sum(
            1
            for value in intent.object_terms
            if value.casefold() in haystack
        )
        return bool(action_match and (object_matches or not intent.object_terms))

    for intent_index, intent in enumerate(intents):
        if find_capabilities is not None:
            apps = [
                app
                for app in (_host_app(host) for host in intent.hosts)
                if app
            ] or [None]
            for app in apps:
                matches = [
                    match
                    for match in batched_project_matches.get(app, [])
                    if matches_intent(match, intent)
                ]
                if not matches:
                    try:
                        matches = find_capabilities(
                            intent.query,
                            app=app,
                            max_results=max(8, min(limit, 24)),
                        )
                    except Exception:
                        matches = []
                for match in matches:
                    name = str(match.get("name") or "")
                    path = str(match.get("source_file") or "")
                    if not name:
                        continue
                    key = (name.casefold(), path.casefold())
                    record = records.setdefault(key, {
                        "qualified_name": name,
                        "signature": str(match.get("signature") or ""),
                        "path": path,
                        "source_excerpt": str(match.get("docstring") or "")[:1600],
                        "kind": "capability",
                        "provider": "project_capability_registry",
                        "provenance": "project_analysis.capabilities",
                        "confidence": "exact" if match.get("signature") else "candidate",
                        "authoritative_signature": _complete_callable_signature(
                            match.get("signature")
                        ),
                        "supports": [],
                        "query_links": [],
                        "capability_relationships": {
                            "requires": list(match.get("requires") or []),
                            "local_calls": list(match.get("local_calls") or []),
                            "unreal_calls": list(match.get("unreal_calls") or []),
                            "operation_keys": list(match.get("operation_keys") or []),
                        },
                        "intent_indexes": [],
                    })
                    record["supports"].append(intent.source_clause)
                    record["query_links"].append(intent.query)
                    record["intent_indexes"].append(intent_index)

        try:
            catalog_matches = _general_registry().lookup(
                intent.query,
                limit=max(6, min(limit, 16)),
            )
        except Exception:
            catalog_matches = []
        for entry in catalog_matches:
            import_module = str(getattr(entry, "import_module", "") or "")
            import_symbol = str(getattr(entry, "import_symbol", "") or "")
            qualified_name = ".".join(
                value for value in (import_module, import_symbol) if value
            ) or str(getattr(entry, "name", "") or "")
            path = str(getattr(entry, "file_path", "") or "")
            if not qualified_name:
                continue
            key = (qualified_name.casefold(), path.casefold())
            record = records.setdefault(key, {
                "qualified_name": qualified_name,
                "signature": "",
                "path": path,
                "source_excerpt": str(getattr(entry, "notes", "") or "")[:1600],
                "kind": str(getattr(entry, "category", "") or "capability"),
                "provider": "general_capability_registry",
                "provenance": "data.capability_registry",
                "confidence": "candidate",
                "authoritative_signature": False,
                "supports": [],
                "query_links": [],
                "capability_relationships": {
                    "requires": list(getattr(entry, "requires", []) or []),
                },
                "intent_indexes": [],
            })
            record["supports"].append(intent.source_clause)
            record["query_links"].append(intent.query)
            record["intent_indexes"].append(intent_index)

    for indexed_record in _indexed_capability_candidates(
        intents,
        limit=max(16, int(limit)),
    ):
        key = (
            str(indexed_record["qualified_name"]).casefold(),
            str(indexed_record["path"]).casefold(),
        )
        existing = records.get(key)
        if existing is None:
            records[key] = indexed_record
            continue
        existing.update({
            "signature": indexed_record["signature"],
            "source_excerpt": (
                indexed_record["source_excerpt"]
                or existing.get("source_excerpt", "")
            ),
            "provider": indexed_record["provider"],
            "provenance": indexed_record["provenance"],
            "confidence": "exact",
            "authoritative_signature": _complete_callable_signature(
                indexed_record["signature"]
            ),
        })
        existing["supports"] = list(dict.fromkeys([
            *existing.get("supports", []),
            *indexed_record["supports"],
        ]))
        existing["query_links"] = list(dict.fromkeys([
            *existing.get("query_links", []),
            *indexed_record["query_links"],
        ]))
        existing["intent_indexes"] = sorted(set([
            *existing.get("intent_indexes", []),
            *indexed_record["intent_indexes"],
        ]))

    normalized = []
    for record in records.values():
        record["supports"] = list(dict.fromkeys(record["supports"]))
        record["query_links"] = list(dict.fromkeys(record["query_links"]))
        record["intent_indexes"] = sorted(set(record["intent_indexes"]))
        normalized.append(record)
    normalized.sort(key=lambda item: (
        0 if item.get("authoritative_signature") else 1,
        -int(item.get("_capability_score") or 0),
        -len(item.get("intent_indexes") or []),
        str(item.get("qualified_name") or "").casefold(),
    ))
    covered_intent_indexes = sorted({
        int(index)
        for record in normalized
        if record.get("authoritative_signature")
        for index in record.get("intent_indexes") or []
    })
    return {
        "schema": "tech_connector.capability_resolution.v2",
        "intents": [asdict(intent) for intent in intents],
        "candidates": normalized[: max(1, int(limit))],
        "covered_intent_indexes": covered_intent_indexes,
        "unresolved_intents": [
            asdict(intent)
            for index, intent in enumerate(intents)
            if index not in covered_intent_indexes
        ],
        "lookup_mode": "batched_with_focused_fallback",
        "needs_reasoning": any(
            not intent.explicit_symbols and len(intent.object_terms) < 2
            for intent in intents
        ),
    }
