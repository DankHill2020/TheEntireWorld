"""Persistent capability inventory and dependency graph for the Capability Acquisition system.

Stores all known capabilities — internal functions, bridges, ingested GitHub tools,
workflows, asset sources, documentation — as CapabilityEntry records.

Seeded from tool_discovery_service on first run. Supports:
- Fast keyword lookup (< 5ms)
- Semantic lookup via nomic-embed-text embeddings (Ollama)
- Dependency graph traversal
- JSON persistence to data/capability_registry.json
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


REGISTRY_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# CapabilityEntry
# ---------------------------------------------------------------------------

@dataclass
class CapabilityEntry:
    """A single known capability registered in the system."""

    id: str
    name: str
    category: str          # internal_function | bridge | workflow | plugin | asset_source | api | docs | generated | ingested_tool
    dcc_hosts: list
    keywords: list
    source: str            # internal | github | marketplace | docs | generated
    file_path: str
    requires: list         # list of CapabilityEntry.id values this depends on
    acquired_at: str
    notes: str
    import_module: str     # Python dotted module path for importlib
    import_symbol: str     # Function or class name within the module
    phase: int             # 1 = automated, 2 = semi-automated/manual
    enabled: bool

    @classmethod
    def from_dict(cls, data: dict) -> "CapabilityEntry":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            category=data.get("category", "internal_function"),
            dcc_hosts=data.get("dcc_hosts", ["*"]),
            keywords=data.get("keywords", []),
            source=data.get("source", "internal"),
            file_path=data.get("file_path", ""),
            requires=data.get("requires", []),
            acquired_at=data.get("acquired_at", ""),
            notes=data.get("notes", ""),
            import_module=data.get("import_module", ""),
            import_symbol=data.get("import_symbol", ""),
            phase=int(data.get("phase", 1)),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def matches_keywords(self, tokens: set) -> bool:
        """Fast keyword intersection check."""
        entry_set = {k.lower() for k in self.keywords}
        entry_set.update(self.name.lower().split("_"))
        entry_set.update(self.name.lower().split())
        entry_set.update(self.notes.lower().split()[:20])
        return bool(tokens & entry_set)


# ---------------------------------------------------------------------------
# Embedding cache
# ---------------------------------------------------------------------------

_EMBEDDING_CACHE: dict = {}


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")[:64]


class CapabilityRegistry:
    """Live capability inventory with keyword + semantic lookup and dependency graph."""

    def __init__(self, registry_path: Path) -> None:
        self._path = Path(registry_path)
        self._entries: dict = {}
        self._seeded = False
        if self._path.exists():
            self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data.get("entries", []):
                entry = CapabilityEntry.from_dict(item)
                self._entries[entry.id] = entry
        except Exception:
            pass

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": REGISTRY_SCHEMA_VERSION,
            "saved_at": _utc_now(),
            "entries": [e.to_dict() for e in self._entries.values()],
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Seeding from internal tools
    # ------------------------------------------------------------------

    def scan_internals(self, roots: list, external_tools_dir: Optional[Path] = None) -> int:
        """Populate registry from internal tools and previously ingested GitHub repos.

        Returns the number of new entries added.
        """
        from services.tool_discovery_service import list_internal_functions, list_ingested_tools

        added = 0

        symbols = list_internal_functions(roots)
        for sym in symbols:
            entry = self._symbol_to_entry(sym, source="internal")
            if entry.id not in self._entries:
                self._entries[entry.id] = entry
                added += 1

        if external_tools_dir and Path(external_tools_dir).exists():
            ingested = list_ingested_tools(Path(external_tools_dir))
            for sym in ingested:
                entry = self._symbol_to_entry(sym, source="github")
                if entry.id not in self._entries:
                    self._entries[entry.id] = entry
                    added += 1

        for bridge_entry in _BUILT_IN_BRIDGE_ENTRIES:
            if bridge_entry.id not in self._entries:
                self._entries[bridge_entry.id] = bridge_entry
                added += 1

        self._seeded = True
        return added

    def _symbol_to_entry(self, symbol: dict, source: str = "internal") -> CapabilityEntry:
        """Convert a tool_discovery_service symbol dict to a CapabilityEntry."""
        name = symbol.get("name", "")
        file_path = symbol.get("file_path", "")
        docstring = symbol.get("docstring", "")
        kind = symbol.get("kind", "function")

        dcc_hosts = _infer_dcc_hosts(file_path + " " + name)
        kw_text = f"{name} {docstring} {file_path}".lower()
        keywords = list(set(re.findall(r"[a-z][a-z0-9_]{2,}", kw_text)))[:40]
        import_module = _file_path_to_module(file_path)

        cap_id = _slug(f"{source}_{name}_{Path(file_path).stem}" if file_path else f"{source}_{name}")
        if cap_id in self._entries:
            cap_id = f"{cap_id}_{abs(hash(file_path + name)) % 10000}"

        return CapabilityEntry(
            id=cap_id,
            name=name,
            category="internal_function" if kind == "function" else "internal_class",
            dcc_hosts=dcc_hosts or ["*"],
            keywords=keywords,
            source=source,
            file_path=file_path,
            requires=[],
            acquired_at=_utc_now(),
            notes=docstring[:300] if docstring else "",
            import_module=import_module,
            import_symbol=name,
            phase=1,
            enabled=True,
        )

    # ------------------------------------------------------------------
    # Registration (post-acquisition)
    # ------------------------------------------------------------------

    def register(self, entry: CapabilityEntry) -> None:
        """Add or update a capability entry."""
        self._entries[entry.id] = entry

    def register_ingested_tool(
        self,
        repo_name: str,
        repo_url: str,
        local_dir: Path,
        symbols: list,
        notes: str = "",
    ) -> list:
        """Register all symbols from an ingested GitHub tool as pipeline-importable capabilities.

        Ensures each tool is discoverable from the pipeline view via import_module + import_symbol.
        Returns the list of registered CapabilityEntry instances.
        """
        entries = []
        for sym in symbols:
            entry = self._symbol_to_entry(sym, source="github")
            # Rebuild with actual acquisition metadata and extra ingestion tags
            entry = CapabilityEntry(
                id=entry.id,
                name=entry.name,
                category="ingested_tool",
                dcc_hosts=entry.dcc_hosts,
                keywords=entry.keywords + [repo_name.lower(), "github", "ingested"],
                source="github",
                file_path=entry.file_path,
                requires=[],
                acquired_at=_utc_now(),
                notes=f"Ingested from {repo_url}. {notes}".strip(),
                import_module=entry.import_module,
                import_symbol=entry.import_symbol,
                phase=1,
                enabled=True,
            )
            self._entries[entry.id] = entry
            entries.append(entry)
        return entries

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, requirement: str, limit: int = 10) -> list:
        """Find capabilities matching a natural language requirement.

        Strategy:
        1. Fast keyword intersection (always, < 5ms)
        2. Semantic embedding similarity via nomic-embed-text (fallback when < 3 results)
        """
        tokens = set(re.findall(r"[a-z][a-z0-9_]{2,}", requirement.lower()))
        scored = []

        for entry in self._entries.values():
            if not entry.enabled:
                continue
            if entry.matches_keywords(tokens):
                entry_kw = {k.lower() for k in entry.keywords}
                score = float(len(tokens & entry_kw))
                if any(t in entry.name.lower() for t in tokens):
                    score += 3.0
                if any(t in entry.category for t in tokens):
                    score += 2.0
                if score > 0:
                    scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        keyword_results = [e for _, e in scored[:limit]]

        if len(keyword_results) < 3:
            semantic = self._semantic_lookup(requirement, limit=limit)
            seen_ids = {e.id for e in keyword_results}
            for e in semantic:
                if e.id not in seen_ids:
                    keyword_results.append(e)
                    seen_ids.add(e.id)

        return keyword_results[:limit]

    def _semantic_lookup(self, requirement: str, limit: int = 5) -> list:
        """Semantic similarity lookup via nomic-embed-text."""
        try:
            req_embedding = _get_embedding(requirement)
            if not req_embedding:
                return []

            scored = []
            for entry in self._entries.values():
                if not entry.enabled:
                    continue
                text = f"{entry.name} {entry.notes} {' '.join(entry.keywords[:10])}"
                emb = _get_embedding(text)
                if emb:
                    sim = _cosine_similarity(req_embedding, emb)
                    if sim > 0.5:
                        scored.append((sim, entry))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [e for _, e in scored[:limit]]
        except Exception:
            return []

    def satisfies(self, requirement: str) -> bool:
        """Return True if any registered enabled capability satisfies the requirement."""
        return len(self.lookup(requirement, limit=1)) > 0

    def all_entries(self) -> list:
        return list(self._entries.values())

    def get(self, capability_id: str) -> Optional[CapabilityEntry]:
        return self._entries.get(capability_id)

    # ------------------------------------------------------------------
    # Dependency graph
    # ------------------------------------------------------------------

    def get_dependency_chain(self, capability_id: str) -> list:
        """Walk the requires graph and return full acquisition order (topological)."""
        visited: set = set()
        result = []

        def _walk(cap_id: str) -> None:
            if cap_id in visited:
                return
            visited.add(cap_id)
            entry = self._entries.get(cap_id)
            if not entry:
                return
            for req_id in entry.requires:
                _walk(req_id)
            result.append(entry)

        _walk(capability_id)
        return result

    def export_graph(self) -> dict:
        """Return the dependency graph as a dict suitable for visualization."""
        nodes = []
        edges = []
        for entry in self._entries.values():
            nodes.append({
                "id": entry.id,
                "name": entry.name,
                "category": entry.category,
                "source": entry.source,
                "enabled": entry.enabled,
            })
            for req_id in entry.requires:
                edges.append({"from": req_id, "to": entry.id})
        return {"nodes": nodes, "edges": edges}

    def stats(self) -> dict:
        entries = list(self._entries.values())
        by_cat: dict = {}
        by_source: dict = {}
        for e in entries:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
            by_source[e.source] = by_source.get(e.source, 0) + 1
        return {
            "total": len(entries),
            "enabled": sum(1 for e in entries if e.enabled),
            "by_category": by_cat,
            "by_source": by_source,
        }


# ---------------------------------------------------------------------------
# Built-in bridge entries
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _make_bridge(id: str, name: str, dcc: str, module: str, cls: str) -> CapabilityEntry:
    return CapabilityEntry(
        id=id, name=name,
        category="bridge",
        dcc_hosts=[dcc],
        keywords=[dcc, "bridge", "connection", "execute", "remote", "live"],
        source="internal",
        file_path=f"bridges/{dcc}/{dcc}_bridge.py",
        requires=[],
        acquired_at=_utc_now(),
        notes=f"Live bridge to {name}.",
        import_module=module,
        import_symbol=cls,
        phase=1,
        enabled=True,
    )


_BUILT_IN_BRIDGE_ENTRIES = [
    _make_bridge("bridge_maya", "Maya Bridge", "maya", "bridges.maya.maya_bridge", "MayaBridge"),
    _make_bridge("bridge_unreal", "Unreal Bridge", "unreal", "bridges.unreal.unreal_bridge", "UnrealBridge"),
    _make_bridge("bridge_blender", "Blender Bridge", "blender", "bridges.blender.blender_bridge", "BlenderBridge"),
    _make_bridge("bridge_substance_painter", "Substance Painter Bridge", "substance_painter",
                 "bridges.substance_painter.substance_painter_bridge", "SubstancePainterBridge"),
    _make_bridge("bridge_motionbuilder", "MotionBuilder Bridge", "motionbuilder",
                 "bridges.motionbuilder.motionbuilder_bridge", "MotionBuilderBridge"),
    _make_bridge("bridge_houdini", "Houdini Bridge", "houdini", "bridges.houdini.houdini_bridge", "HoudiniBridge"),
    _make_bridge("bridge_unity", "Unity Bridge", "unity", "bridges.unity.unity_bridge", "UnityBridge"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DCC_HOST_PATTERNS = {
    "maya": ("maya", "cmds", "pymel", "mel"),
    "unreal": ("unreal", "ue5", "ue4", "blueprint", "uasset"),
    "blender": ("blender", "bpy"),
    "substance_painter": ("substance", "painter"),
    "motionbuilder": ("motionbuilder", "mobu"),
    "houdini": ("houdini", "hou", "vex"),
    "unity": ("unity", "gameobject", "prefab"),
}


def _infer_dcc_hosts(text: str) -> list:
    lower = text.lower()
    hosts = []
    for host, patterns in _DCC_HOST_PATTERNS.items():
        if any(p in lower for p in patterns):
            hosts.append(host)
    return hosts


def _file_path_to_module(file_path: str) -> str:
    """Convert an absolute file path to a dotted Python module path (best-effort)."""
    if not file_path:
        return ""
    try:
        p = Path(file_path)
        parts = list(p.with_suffix("").parts)
        module_parts = []
        for i in range(len(parts) - 1, -1, -1):
            part = parts[i]
            module_parts.insert(0, part)
            parent = Path(*parts[:i]) if i > 0 else Path(".")
            if not (parent / "__init__.py").exists():
                break
        return ".".join(module_parts).strip(".")
    except Exception:
        return ""


# _utc_now is defined earlier (above _BUILT_IN_BRIDGE_ENTRIES) — do not redefine here.


def _get_embedding(text: str) -> list:
    """Get nomic-embed-text embedding via Ollama API. Results are cached."""
    key = text[:200]
    if key in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[key]
    try:
        import urllib.request
        import json as _json
        from services.ollama_service import OLLAMA_BASE_URL, EMBEDDING_MODEL
        payload = _json.dumps({"model": EMBEDDING_MODEL, "prompt": text}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(req, timeout=3) as resp:
            result = _json.loads(resp.read())
        emb = result.get("embedding", [])
        if emb:
            _EMBEDDING_CACHE[key] = emb
        return emb
    except Exception:
        return []


def _cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
