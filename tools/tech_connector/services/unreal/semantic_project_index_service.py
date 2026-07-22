"""Incremental semantic index for a live Unreal project."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.bridges.unreal.unreal_intelligence import ensure_project, resolve_project_root
from tech_connector.dcc_intelligence.store import IntelligenceStore


DCC = "Unreal"
COLLECTOR = "tech_connector.bridges.unreal.unreal_semantic_index_collector.collect_semantic_project_batch"
DETAIL_COLLECTOR = "tech_connector.bridges.unreal.unreal_semantic_index_collector.collect_semantic_asset_details"


def infer_required_index_domains(request: str) -> list[str]:
    lowered = (request or "").lower()
    domains = ["asset_catalog", "asset_dependencies", "blueprint_topology"]
    if any(term in lowered for term in ("anim", "montage", "motion match", "skeleton", "retarget")):
        domains.extend(("animation_metadata", "project_art_sources"))
    if any(term in lowered for term in ("cpp", "c++", "plugin", "native", "python exposed")):
        domains.append("cpp_source")
    if any(term in lowered for term in ("play", "pie", "runtime", "functional", "verify", "test", "working")):
        domains.append("runtime_world")
    return list(dict.fromkeys(domains))


def open_semantic_store(project_root: str | None = None) -> IntelligenceStore:
    root = resolve_project_root(project_root)
    return IntelligenceStore(root / ".ai_studio" / "intelligence" / "unreal_semantic_index.sqlite")


def _asset_key(path: str) -> str:
    return "asset:" + str(path or "")


def _scan_project_art_sources(
    store: IntelligenceStore,
    project_id: int,
    *,
    project_root: str | None,
    live_project_dir: str,
) -> dict[str, Any]:
    """Index external DCC source files that can satisfy Unreal asset gaps."""

    candidates = []
    for anchor in (Path(project_root or ".").resolve(), Path(live_project_dir or ".").resolve()):
        candidates.extend((anchor / "ArtSource", anchor.parent / "ArtSource", anchor.parent / "artsource"))
    roots = [path for path in dict.fromkeys(candidates) if path.is_dir()]
    extensions = {".fbx", ".bvh", ".ma", ".mb"}
    files = sorted(
        {
            path
            for root in roots
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in extensions
        },
        key=lambda path: str(path).lower(),
    )
    evidence_path = Path(project_root or ".").resolve() / ".ai_studio" / "intelligence" / "artsource_asset_evidence.json"
    evidence = {}
    if evidence_path.is_file():
        try:
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence = {str(Path(key).resolve()).lower(): dict(value) for key, value in (payload.get("assets") or {}).items()}
        except (OSError, ValueError, TypeError):
            evidence = {}
    with store.conn:
        store.conn.execute(
            "DELETE FROM semantic_relations WHERE project_id=? AND dcc=? AND (source_key LIKE 'artsource:%' OR target_key LIKE 'artsource:%')",
            (project_id, DCC),
        )
        store.conn.execute(
            "DELETE FROM semantic_entities WHERE project_id=? AND dcc=? AND entity_key LIKE 'artsource:%'",
            (project_id, DCC),
        )
    kinds = {"retarget": "retarget_rig", "mocap_rig": "mocap_rig", "animation": "animation_source"}
    for path in files:
        stat = path.stat()
        normalized = path.as_posix()
        lowered = normalized.lower()
        kind = next((value for token, value in kinds.items() if token in lowered), "dcc_source_asset")
        metadata = {
            "suffix": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "project_local": True,
            **evidence.get(str(path.resolve()).lower(), {}),
        }
        fingerprint = hashlib.sha256(
            f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
        ).hexdigest()
        store.upsert_semantic_entity(
            project_id,
            DCC,
            entity_key="artsource:" + normalized,
            entity_kind=kind,
            display_name=path.name,
            path=normalized,
            class_name=path.suffix.lstrip(".").upper(),
            fingerprint=fingerprint,
            confidence=float(metadata.get("confidence") or 0.7),
            source="project_art_source_scan",
            metadata=metadata,
        )
    return {
        "complete": bool(roots),
        "indexed": len(files),
        "roots": [str(path) for path in roots],
        "evidence_manifest": str(evidence_path) if evidence_path.is_file() else "",
    }


def _scan_unreal_source(
    store: IntelligenceStore,
    project_id: int,
    *,
    project_root: str | None,
    live_project_dir: str,
    engine_dir: str,
) -> dict[str, Any]:
    roots = [
        Path(live_project_dir) / "Source",
        Path(live_project_dir) / "Plugins",
        Path(project_root or ".") / "Source",
        Path(engine_dir) / "Plugins" / "AIStudioBridge" / "Source",
    ]
    roots = list(dict.fromkeys(path.resolve() for path in roots if str(path)))
    extensions = {".h", ".hpp", ".cpp", ".cc", ".cs", ".uplugin", ".uproject"}
    files: list[Path] = []
    errors: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            files.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in extensions
                and not {"Binaries", "Intermediate", "Saved"}.intersection(path.parts)
            )
        except OSError as exc:
            errors.append(f"{root}: {exc}")
    files = sorted(set(files), key=lambda path: str(path).lower())
    with store.conn:
        store.conn.execute(
            "DELETE FROM semantic_relations WHERE project_id=? AND dcc=? AND (source_key LIKE 'source:%' OR target_key LIKE 'source:%')",
            (project_id, DCC),
        )
        store.conn.execute(
            "DELETE FROM semantic_entities WHERE project_id=? AND dcc=? AND entity_key LIKE 'source:%'",
            (project_id, DCC),
        )
    entity_count = 0
    relation_count = 0
    for path in files:
        try:
            source_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        normalized = path.as_posix()
        file_key = "source:" + normalized
        fingerprint = hashlib.sha256(source_text.encode("utf-8", errors="replace")).hexdigest()
        store.upsert_semantic_entity(
            project_id,
            DCC,
            entity_key=file_key,
            entity_kind="source_file",
            display_name=path.name,
            path=normalized,
            class_name="",
            fingerprint=fingerprint,
            confidence=1.0,
            source="filesystem_source_scan",
            metadata={"suffix": path.suffix.lower(), "size": len(source_text)},
        )
        entity_count += 1
        for include in re.findall(r'^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]', source_text, re.MULTILINE):
            store.upsert_semantic_relation(
                project_id,
                DCC,
                source_key=file_key,
                relation="includes",
                target_key="source_include:" + include,
                confidence=0.9,
                source="filesystem_source_scan",
            )
            relation_count += 1
        class_pattern = re.compile(
            r"U(?:CLASS|STRUCT|INTERFACE)\s*\([^)]*\)\s*(?:class|struct)\s+(?:\w+_API\s+)?(\w+)(?:\s*:\s*public\s+([\w:]+))?",
            re.MULTILINE,
        )
        for class_name, base_class in class_pattern.findall(source_text):
            class_key = f"{file_key}::class:{class_name}"
            store.upsert_semantic_entity(
                project_id,
                DCC,
                entity_key=class_key,
                entity_kind="cpp_reflected_class",
                display_name=class_name,
                path=normalized,
                class_name=class_name,
                parent_key=file_key,
                fingerprint="",
                confidence=0.9,
                source="unreal_header_reflection_scan",
                metadata={"base_class": base_class},
            )
            store.upsert_semantic_relation(
                project_id,
                DCC,
                source_key=file_key,
                relation="declares_class",
                target_key=class_key,
                confidence=0.9,
                source="unreal_header_reflection_scan",
            )
            entity_count += 1
            relation_count += 1
        function_pattern = re.compile(
            r"UFUNCTION\s*\(([^)]*)\)\s*(?:virtual\s+)?[\w:<>,*&\s]+?\s+(\w+)\s*\(([^;{}]*)\)",
            re.MULTILINE,
        )
        for specifiers, function_name, parameters in function_pattern.findall(source_text):
            function_key = f"{file_key}::function:{function_name}"
            store.upsert_semantic_entity(
                project_id,
                DCC,
                entity_key=function_key,
                entity_kind="cpp_reflected_function",
                display_name=function_name,
                path=normalized,
                parent_key=file_key,
                fingerprint="",
                confidence=0.85,
                source="unreal_header_reflection_scan",
                metadata={"specifiers": specifiers.strip(), "parameters": parameters.strip()},
            )
            store.upsert_semantic_relation(
                project_id,
                DCC,
                source_key=file_key,
                relation="declares_function",
                target_key=function_key,
                confidence=0.85,
                source="unreal_header_reflection_scan",
            )
            entity_count += 1
            relation_count += 1
    return {
        "complete": not errors,
        "indexed_files": len(files),
        "entities": entity_count,
        "relations": relation_count,
        "roots": [str(path) for path in roots if path.exists()],
        "errors": errors,
    }


def _persist_detail(store, project_id: int, detail: dict[str, Any]) -> dict[str, int]:
    counts = {"entities": 0, "relations": 0, "graphs": 0, "nodes": 0, "pins": 0}
    asset_path = str(detail.get("asset_path") or "")
    parent = _asset_key(asset_path)
    if not asset_path or detail.get("kind") in {"missing", "error"}:
        return counts
    child_prefix = parent + "::%"
    with store.conn:
        store.conn.execute(
            "DELETE FROM semantic_relations WHERE project_id=? AND dcc=? AND (source_key LIKE ? OR target_key LIKE ?)",
            (project_id, DCC, child_prefix, child_prefix),
        )
        store.conn.execute(
            """
            DELETE FROM semantic_relations
            WHERE project_id=? AND dcc=? AND source_key=? AND relation IN (
                'inherits', 'uses_skeleton', 'owns_variable', 'owns_function', 'owns_component', 'owns_graph'
            )
            """,
            (project_id, DCC, parent),
        )
        store.conn.execute(
            "DELETE FROM semantic_entities WHERE project_id=? AND dcc=? AND entity_key LIKE ?",
            (project_id, DCC, child_prefix),
        )
    store.upsert_semantic_entity(
        project_id,
        DCC,
        entity_key=parent,
        entity_kind=str(detail.get("kind") or "asset_detail"),
        display_name=asset_path.rsplit("/", 1)[-1],
        path=asset_path,
        class_name=str(detail.get("class_name") or ""),
        fingerprint=str(detail.get("fingerprint") or ""),
        confidence=1.0,
        source="live_unreal_deep_inspection",
        metadata={key: value for key, value in detail.items() if key != "graphs"},
    )
    counts["entities"] += 1
    parent_class = str(detail.get("parent_class") or "")
    if parent_class:
        store.upsert_semantic_relation(
            project_id,
            DCC,
            source_key=parent,
            relation="inherits",
            target_key="class:" + parent_class,
            confidence=1.0,
            source="live_unreal_blueprint_reflection",
        )
        counts["relations"] += 1
    for category, kind in (("variables", "variable"), ("functions", "function"), ("components", "component")):
        for index, row in enumerate(detail.get(category) or []):
            name = str(dict(row).get("name") or dict(row).get("variable") or index)
            key = f"{parent}::{kind}:{name}"
            store.upsert_semantic_entity(
                project_id,
                DCC,
                entity_key=key,
                entity_kind=kind,
                display_name=name,
                path=asset_path,
                class_name=str(dict(row).get("class") or ""),
                parent_key=parent,
                fingerprint="",
                confidence=1.0,
                source="live_unreal_blueprint_reflection",
                metadata=dict(row),
            )
            store.upsert_semantic_relation(
                project_id,
                DCC,
                source_key=parent,
                relation="owns_" + kind,
                target_key=key,
                confidence=1.0,
                source="live_unreal_blueprint_reflection",
            )
            counts["entities"] += 1
            counts["relations"] += 1
    for graph in detail.get("graphs") or []:
        graph = dict(graph or {})
        graph_name = str(graph.get("name") or "Graph")
        graph_key = f"{parent}::graph:{graph_name}"
        store.upsert_semantic_entity(
            project_id,
            DCC,
            entity_key=graph_key,
            entity_kind="blueprint_graph",
            display_name=graph_name,
            path=asset_path,
            parent_key=parent,
            fingerprint=str(graph.get("fingerprint") or ""),
            confidence=1.0,
            source="live_unreal_graph_readback",
            metadata={"errors": graph.get("errors") or [], "node_count": len(graph.get("nodes") or [])},
        )
        store.upsert_semantic_relation(
            project_id,
            DCC,
            source_key=parent,
            relation="owns_graph",
            target_key=graph_key,
            confidence=1.0,
            source="live_unreal_graph_readback",
        )
        counts["entities"] += 1
        counts["relations"] += 1
        counts["graphs"] += 1
        node_keys: dict[str, str] = {}
        for index, node in enumerate(graph.get("nodes") or []):
            node = dict(node or {})
            node_name = str(node.get("name") or index)
            node_key = f"{graph_key}::node:{node_name}"
            node_keys[node_name] = node_key
            store.upsert_semantic_entity(
                project_id,
                DCC,
                entity_key=node_key,
                entity_kind="blueprint_node",
                display_name=str(node.get("title") or node_name),
                path=asset_path,
                class_name=str(node.get("class") or ""),
                parent_key=graph_key,
                fingerprint="",
                confidence=1.0,
                source="live_unreal_graph_readback",
                metadata={"node_name": node_name, "pin_count": len(node.get("pins") or [])},
            )
            store.upsert_semantic_relation(
                project_id,
                DCC,
                source_key=graph_key,
                relation="owns_node",
                target_key=node_key,
                confidence=1.0,
                source="live_unreal_graph_readback",
            )
            counts["entities"] += 1
            counts["relations"] += 1
            counts["nodes"] += 1
            for pin_index, pin in enumerate(node.get("pins") or []):
                pin = dict(pin or {})
                pin_name = str(pin.get("name") or pin_index)
                pin_key = f"{node_key}::pin:{pin.get('direction') or 'unknown'}:{pin_name}"
                store.upsert_semantic_entity(
                    project_id,
                    DCC,
                    entity_key=pin_key,
                    entity_kind="blueprint_pin",
                    display_name=pin_name,
                    path=asset_path,
                    parent_key=node_key,
                    fingerprint="",
                    confidence=1.0,
                    source="live_unreal_graph_readback",
                    metadata={"direction": pin.get("direction"), "value": pin.get("value")},
                )
                store.upsert_semantic_relation(
                    project_id,
                    DCC,
                    source_key=node_key,
                    relation="owns_pin",
                    target_key=pin_key,
                    confidence=1.0,
                    source="live_unreal_graph_readback",
                )
                counts["entities"] += 1
                counts["relations"] += 1
                counts["pins"] += 1
                for link in pin.get("links") or []:
                    target_node = node_keys.get(str(dict(link).get("node") or ""))
                    if not target_node:
                        target_node = f"{graph_key}::node:{dict(link).get('node') or 'unknown'}"
                    target_pin = f"{target_node}::pin:unknown:{dict(link).get('pin') or 'unknown'}"
                    store.upsert_semantic_relation(
                        project_id,
                        DCC,
                        source_key=pin_key,
                        relation="connected_to",
                        target_key=target_pin,
                        confidence=1.0,
                        source="live_unreal_graph_readback",
                    )
                    counts["relations"] += 1
    skeleton = str(detail.get("skeleton") or "")
    if skeleton:
        store.upsert_semantic_relation(
            project_id,
            DCC,
            source_key=parent,
            relation="uses_skeleton",
            target_key=_asset_key(skeleton),
            confidence=1.0,
            source="live_unreal_animation_reflection",
        )
        counts["relations"] += 1
    return counts


def refresh_unreal_semantic_project_index(
    project_root: str | None = None,
    *,
    detail_paths: Iterable[str] | None = None,
    batch_size: int = 250,
    max_batches: int | None = None,
    include_dependencies: bool = True,
    reload_collector: bool = True,
    auto_detail_changed: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Refresh the full asset catalog and deep-index the requested assets."""

    detail_paths = list(dict.fromkeys(str(value) for value in detail_paths or [] if value))
    bridge = UnrealBridge()
    store = open_semantic_store(project_root)
    started = datetime.now(timezone.utc)
    totals = {"assets": 0, "relations": 0, "details": 0, "graphs": 0, "nodes": 0, "pins": 0}
    errors: list[str] = []
    cursor = 0
    total_assets = 0
    seen_asset_paths: set[str] = set()
    complete = False
    batch_count = 0
    live_project_dir = ""
    engine_dir = ""
    changed_detail_paths: list[str] = []
    project = ensure_project(store, project_root)
    excluded_paths = store.semantic_excluded_paths(project.id, DCC)
    try:
        if reload_collector:
            reload_response = bridge.execute_python(
                "import importlib; from tech_connector.bridges.unreal import unreal_semantic_index_collector as m; importlib.invalidate_caches(); importlib.reload(m)",
                timeout=min(timeout, 30.0),
                reset_globals=True,
            )
            if not reload_response.get("ok"):
                errors.append(
                    "Semantic collector reload failed: "
                    + str(reload_response.get("error") or reload_response.get("errors") or "unknown error")
                )
        while not complete and (max_batches is None or batch_count < max_batches):
            response = bridge.safe_call(
                COLLECTOR,
                args=[cursor, batch_size, detail_paths if batch_count == 0 else [], include_dependencies],
                timeout=timeout,
                retries=0,
                label="semantic_project_index_batch",
            )
            payload = response.get("data") or response.get("result") or {}
            if not response.get("ok") or not isinstance(payload, dict) or not payload.get("ok"):
                errors.append(str(response.get("error") or payload.get("error") or "Unreal semantic batch failed."))
                break
            total_assets = int(payload.get("total_assets") or total_assets)
            live_project_dir = str(payload.get("project_dir") or live_project_dir)
            engine_dir = str(payload.get("engine_dir") or engine_dir)
            for row in payload.get("assets") or []:
                row = dict(row or {})
                path = str(row.get("package_name") or "")
                seen_asset_paths.add(path)
                if path in excluded_paths:
                    continue
                existing_asset = store.conn.execute(
                    "SELECT content_hash FROM assets WHERE project_id=? AND dcc=? AND asset_path=?",
                    (project.id, DCC, path),
                ).fetchone()
                if (
                    auto_detail_changed
                    and existing_asset
                    and str(existing_asset["content_hash"] or "") != str(row.get("fingerprint") or "")
                    and (
                        "Blueprint" in str(row.get("class_name") or "")
                        or str(row.get("class_name") or "") in {"AnimSequence", "AnimMontage", "BlendSpace", "PoseAsset"}
                    )
                ):
                    changed_detail_paths.append(path)
                key = _asset_key(path)
                store.upsert_asset(
                    project.id,
                    DCC,
                    asset_path=path,
                    asset_name=str(row.get("asset_name") or path.rsplit("/", 1)[-1]),
                    asset_type=str(row.get("class_name") or "Asset"),
                    package_path=str(row.get("package_path") or ""),
                    class_name=str(row.get("class_name") or ""),
                    content_hash=str(row.get("fingerprint") or ""),
                    metadata={"tags": row.get("tags") or {}, "source": "live_unreal_asset_registry"},
                )
                existing = store.conn.execute(
                    "SELECT entity_kind FROM semantic_entities WHERE project_id=? AND dcc=? AND entity_key=?",
                    (project.id, DCC, key),
                ).fetchone()
                if not existing or existing["entity_kind"] == "unreal_asset":
                    store.upsert_semantic_entity(
                        project.id,
                        DCC,
                        entity_key=key,
                        entity_kind="unreal_asset",
                        display_name=str(row.get("asset_name") or ""),
                        path=path,
                        class_name=str(row.get("class_name") or ""),
                        fingerprint=str(row.get("fingerprint") or ""),
                        confidence=1.0,
                        source="live_unreal_asset_registry",
                        metadata={"package_path": row.get("package_path"), "tags": row.get("tags") or {}},
                    )
                totals["assets"] += 1
                for dependency in row.get("dependencies") or []:
                    store.upsert_semantic_relation(
                        project.id,
                        DCC,
                        source_key=key,
                        relation="depends_on",
                        target_key=_asset_key(str(dependency)),
                        confidence=1.0,
                        source="live_unreal_asset_registry",
                    )
                    totals["relations"] += 1
            for detail in payload.get("details") or []:
                if str(dict(detail or {}).get("asset_path") or "") in excluded_paths:
                    continue
                counts = _persist_detail(store, project.id, dict(detail or {}))
                totals["details"] += 1
                for key in ("relations", "graphs", "nodes", "pins"):
                    totals[key] += counts[key]
            cursor = int(payload.get("next_cursor") or cursor)
            complete = bool(payload.get("complete"))
            batch_count += 1
            if not payload.get("assets") and not complete:
                errors.append("Semantic collector made no cursor progress.")
                break
        automatic_details = [
            path for path in dict.fromkeys(changed_detail_paths) if path not in detail_paths and path not in excluded_paths
        ]
        if automatic_details:
            response = bridge.safe_call(
                DETAIL_COLLECTOR,
                args=[automatic_details[:100]],
                timeout=timeout,
                retries=0,
                label="semantic_project_changed_details",
            )
            payload = response.get("data") or response.get("result") or {}
            if response.get("ok") and isinstance(payload, dict) and payload.get("ok"):
                for detail in payload.get("details") or []:
                    counts = _persist_detail(store, project.id, dict(detail or {}))
                    totals["details"] += 1
                    for key in ("relations", "graphs", "nodes", "pins"):
                        totals[key] += counts[key]
            else:
                errors.append(str(response.get("error") or payload.get("error") or "Changed-asset detail refresh failed."))
        totals["changed_assets"] = len(changed_detail_paths)
        totals["auto_detailed_changed_assets"] = min(len(automatic_details), 100)
        if complete:
            stale_rows = store.conn.execute(
                "SELECT asset_path FROM assets WHERE project_id=? AND dcc=?",
                (project.id, DCC),
            ).fetchall()
            stale_paths = [str(row["asset_path"]) for row in stale_rows if str(row["asset_path"]) not in seen_asset_paths]
            with store.conn:
                for stale_path in stale_paths:
                    prefix = _asset_key(stale_path)
                    store.conn.execute(
                        "DELETE FROM semantic_relations WHERE project_id=? AND dcc=? AND (source_key LIKE ? OR target_key LIKE ?)",
                        (project.id, DCC, prefix + "%", prefix + "%"),
                    )
                    store.conn.execute(
                        "DELETE FROM semantic_entities WHERE project_id=? AND dcc=? AND entity_key LIKE ?",
                        (project.id, DCC, prefix + "%"),
                    )
                    store.conn.execute(
                        "DELETE FROM assets WHERE project_id=? AND dcc=? AND asset_path=?",
                        (project.id, DCC, stale_path),
                    )
            totals["removed_stale_assets"] = len(stale_paths)
        cpp_coverage = _scan_unreal_source(
            store,
            project.id,
            project_root=project_root,
            live_project_dir=live_project_dir,
            engine_dir=engine_dir,
        )
        totals["source_entities"] = int(cpp_coverage.get("entities") or 0)
        totals["source_relations"] = int(cpp_coverage.get("relations") or 0)
        art_source_coverage = _scan_project_art_sources(
            store,
            project.id,
            project_root=project_root,
            live_project_dir=live_project_dir,
        )
        totals["art_source_assets"] = int(art_source_coverage.get("indexed") or 0)
        blueprint_total = store.conn.execute(
            "SELECT COUNT(*) FROM assets WHERE project_id=? AND lower(class_name) LIKE '%blueprint%'",
            (project.id,),
        ).fetchone()[0]
        blueprint_detailed = store.conn.execute(
            "SELECT COUNT(*) FROM semantic_entities WHERE project_id=? AND entity_kind='blueprint'",
            (project.id,),
        ).fetchone()[0]
        animation_total = store.conn.execute(
            "SELECT COUNT(*) FROM assets WHERE project_id=? AND class_name IN ('AnimSequence','AnimMontage','BlendSpace','PoseAsset')",
            (project.id,),
        ).fetchone()[0]
        animation_detailed = store.conn.execute(
            "SELECT COUNT(*) FROM semantic_entities WHERE project_id=? AND entity_kind='animation'",
            (project.id,),
        ).fetchone()[0]
        coverage = {
            "asset_catalog": {"complete": complete, "indexed": totals["assets"], "total": total_assets},
            "asset_dependencies": {"complete": bool(complete and include_dependencies)},
            "blueprint_topology": {
                "complete": bool(blueprint_total and blueprint_detailed >= blueprint_total),
                "indexed": blueprint_detailed,
                "total": blueprint_total,
            },
            "animation_metadata": {
                "complete": bool(animation_total and animation_detailed >= animation_total),
                "indexed": animation_detailed,
                "total": animation_total,
            },
            "cpp_source": cpp_coverage,
            "project_art_sources": art_source_coverage,
            "runtime_world": {"complete": False, "reason": "Requires an active PIE scenario observation."},
        }
        status = "complete" if complete and not errors else ("partial" if totals["assets"] else "failed")
        run_id = store.add_semantic_index_run(
            project.id,
            DCC,
            run_kind="full" if max_batches is None else "bounded_incremental",
            status=status,
            coverage=coverage,
            errors=errors,
            metadata={"counts": totals, "batch_count": batch_count, "detail_paths": detail_paths},
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "ok": status != "failed",
            "status": status,
            "project_id": project.id,
            "db_path": str(store.db_path),
            "run_id": run_id,
            "started_at": started.isoformat(),
            "coverage": coverage,
            "counts": totals,
            "errors": errors,
        }
    finally:
        store.close()


def exclude_unreal_semantic_paths(
    asset_paths: Iterable[str], *, reason: str, project_root: str | None = None, source: str = "user"
) -> dict[str, Any]:
    """Exclude retired or invalid assets from retrieval even if Unreal still has them loaded."""

    paths = list(dict.fromkeys(str(value).split(".", 1)[0] for value in asset_paths if value))
    store = open_semantic_store(project_root)
    try:
        project = ensure_project(store, project_root)
        for path in paths:
            store.exclude_semantic_path(
                project.id,
                DCC,
                path,
                reason=reason,
                source=source,
                metadata={"explicit": True},
            )
        return {"ok": True, "excluded": paths, "reason": reason, "source": source}
    finally:
        store.close()


def record_unreal_runtime_observation(
    scenario_key: str,
    *,
    status: str,
    assertions: dict[str, Any],
    evidence: dict[str, Any],
    subject_key: str = "",
    project_root: str | None = None,
) -> dict[str, Any]:
    """Persist task-specific PIE evidence; compile success alone is not runtime proof."""

    store = open_semantic_store(project_root)
    try:
        project = ensure_project(store, project_root)
        observation_id = store.add_runtime_observation(
            project.id,
            DCC,
            scenario_key=scenario_key,
            subject_key=subject_key,
            status=status,
            assertions=assertions,
            evidence=evidence,
        )
        return {"ok": True, "observation_id": observation_id, "scenario_key": scenario_key, "status": status}
    finally:
        store.close()


def assess_project_visibility(
    required_domains: Iterable[str],
    project_root: str | None = None,
    *,
    scenario_key: str = "",
    relevant_paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Make partial sight explicit and recommend knowledge acquisition."""

    store = open_semantic_store(project_root)
    try:
        project = ensure_project(store, project_root)
        run = store.latest_semantic_index_run(project.id, DCC) or {}
        coverage = dict(run.get("coverage") or {})
        relevant = list(dict.fromkeys(str(path).split(".", 1)[0] for path in relevant_paths or [] if path))
        if relevant:
            placeholders = ",".join("?" for _ in relevant)
            rows = store.conn.execute(
                f"SELECT path, entity_kind, metadata_json FROM semantic_entities WHERE project_id=? AND dcc=? AND path IN ({placeholders})",
                (project.id, DCC, *relevant),
            ).fetchall()
            kinds_by_path: dict[str, set[str]] = {}
            for row in rows:
                kinds_by_path.setdefault(str(row["path"]), set()).add(str(row["entity_kind"]))
            blueprint_paths = [path for path in relevant if "blueprint" in kinds_by_path.get(path, set())]
            unresolved_paths = [path for path in relevant if not kinds_by_path.get(path)]
            if blueprint_paths or unresolved_paths:
                missing_blueprints = [
                    path for path in relevant if "blueprint" not in kinds_by_path.get(path, set())
                ]
                coverage["blueprint_topology"] = {
                    "complete": not missing_blueprints,
                    "scope": "task_relevant_paths",
                    "indexed": blueprint_paths,
                    "missing": missing_blueprints,
                }
            animation_paths = [path for path in relevant if "animation" in kinds_by_path.get(path, set())]
            if animation_paths:
                missing_animation = [
                    path for path in relevant
                    if path in animation_paths and "animation" not in kinds_by_path.get(path, set())
                ]
                coverage["animation_metadata"] = {
                    "complete": not missing_animation,
                    "scope": "task_relevant_paths",
                    "indexed": animation_paths,
                    "missing": missing_animation,
                }
        if scenario_key:
            observation = store.conn.execute(
                """
                SELECT * FROM runtime_observations
                WHERE project_id=? AND dcc=? AND scenario_key=?
                ORDER BY id DESC LIMIT 1
                """,
                (project.id, DCC, scenario_key),
            ).fetchone()
            coverage["runtime_world"] = {
                "complete": bool(observation and str(observation["status"]).lower() == "passed"),
                "scenario_key": scenario_key,
                "latest_status": str(observation["status"]) if observation else "missing",
                "reason": "A matching passed PIE observation is required.",
            }
        required = list(dict.fromkeys(str(value) for value in required_domains if value))
        gaps = []
        for domain in required:
            row = dict(coverage.get(domain) or {})
            if not row.get("complete"):
                gaps.append({"domain": domain, "coverage": row, "reason": row.get("reason") or "Index coverage is incomplete."})
        return {
            "ok": not gaps,
            "sight": "complete" if not gaps else "partial",
            "required_domains": required,
            "relevant_paths": relevant,
            "gaps": gaps,
            "latest_run": run,
            "knowledge_choice": {
                "required": bool(gaps),
                "recommended": "add_knowledge_first" if gaps else "use_indexed_knowledge",
                "options": ["add_knowledge_first", "run_with_current_knowledge"] if gaps else [],
            },
        }
    finally:
        store.close()


def query_semantic_project_index(
    query: str, project_root: str | None = None, *, limit: int = 40
) -> dict[str, Any]:
    store = open_semantic_store(project_root)
    try:
        project = ensure_project(store, project_root)
        terms = [value.lower() for value in query.replace("/", " ").replace("_", " ").split() if len(value) > 2]
        candidates: dict[str, dict[str, Any]] = {}
        for term in terms:
            for row in store.search_semantic_entities(project.id, DCC, term, limit=max(100, limit * 4)):
                candidates[row["entity_key"]] = row
        kind_weight = {
            "blueprint": 8,
            "blueprint_graph": 7,
            "blueprint_node": 6,
            "function": 5,
            "variable": 5,
            "component": 5,
            "animation": 5,
            "blueprint_pin": 3,
            "unreal_asset": 1,
        }
        scored = []
        normalized_query = " ".join(terms)
        for row in candidates.values():
            name = str(row.get("display_name") or "").lower().replace("_", " ")
            path = str(row.get("path") or "").lower().replace("_", " ")
            key = str(row.get("entity_key") or "").lower().replace("_", " ")
            metadata = json.dumps(row.get("metadata") or {}, default=str).lower().replace("_", " ")
            hit_count = sum(1 for term in terms if term in (name + " " + path + " " + key + " " + metadata))
            score = hit_count * 10 + kind_weight.get(str(row.get("entity_kind") or ""), 0)
            if normalized_query and normalized_query in name:
                score += 50
            if normalized_query and normalized_query in path:
                score += 25
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("entity_key") or "")))
        entities = [row for _score, row in scored[:limit]]
        relations = store.semantic_relations_for(
            project.id, DCC, [row["entity_key"] for row in entities[:limit]], limit=limit * 3
        )
        return {
            "ok": True,
            "query": query,
            "entities": entities[:limit],
            "relations": relations,
            "latest_run": store.latest_semantic_index_run(project.id, DCC),
        }
    finally:
        store.close()
