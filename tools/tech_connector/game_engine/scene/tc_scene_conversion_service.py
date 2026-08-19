"""Convert bridge scene packets into standalone Tech Connector scenes."""

from __future__ import annotations

import array
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import time
import threading
from typing import Any

from tech_connector.game_engine.deformation.deformation_contract import normalize_deformation_binding
from tech_connector.game_engine.scene.federated_scene_service import (
    EditableRigGraph,
    FederatedSceneDocument,
    save_federated_scene,
)
from tech_connector.game_engine.authoring.rig_topology_contract import normalize_rig_topology
from tech_connector.game_engine.scene.coordinate_space_service import provider_bbox_to_shared, provider_native_to_shared
from tech_connector.game_engine.scene.source_conversion_adapter_service import conversion_readiness
from tech_connector.game_engine.scene.tc_native_scene_compiler_service import (
    compile_graph_to_tc_native,
    stable_tc_id,
)
from tech_connector.game_engine.runtime.tc_runtime_authoring_service import runtime_authoring_contract


EMBEDDED_SCENE_SNAPSHOT_BLOB = "conversion/tc_native_scene_snapshot.json"
CONVERSION_SCHEMA = "tech_connector.scene_conversion_report.v1"
_MAYA_TOPOLOGY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_MAYA_TOPOLOGY_CACHE_LOCK = threading.Lock()
_MAYA_TOPOLOGY_CACHE_LIMIT = 4


@dataclass
class TCSceneConversionResult:
    """A standalone TC scene plus its binary sidecars and migration report."""

    document: FederatedSceneDocument
    blobs: dict[str, bytes]
    report: dict[str, Any]
    scene_snapshot: dict[str, Any]

    def save(self, path: str | Path) -> Path:
        return save_federated_scene(path, self.document, blobs=self.blobs)


def convert_to_tc(
    *,
    scene_snapshot: dict[str, Any] | None = None,
    rig_topology: dict[str, Any] | None = None,
    deformation_binding: dict[str, Any] | None = None,
    source_provider: str = "maya",
    source_native_id: str = "",
    scope: str = "scene",
    include_animation: bool = True,
    include_materials: bool = True,
    port: int | None = None,
    output_path: str | Path | None = None,
    progress_callback: Any = None,
    cancel_event: Any = None,
) -> TCSceneConversionResult:
    """Convert supplied packets, or capture a live Maya session when ``port`` is set."""
    provider = str(source_provider or "maya").strip().lower().split(":", 1)[0]
    capture_issues: list[dict[str, Any]] = []
    if scene_snapshot is None:
        if provider != "maya" or not port:
            raise ValueError("A scene snapshot or a live Maya command port is required.")
        scene_snapshot, rig_topology, deformation_binding, capture_issues = capture_maya_scene(
            int(port),
            source_native_id=source_native_id,
            scope=scope,
            include_animation=include_animation,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
    _raise_if_cancelled(cancel_event)
    _emit_progress(progress_callback, 96, "Compiling validated TC scene chunks")
    result = convert_scene_packets_to_tc(
        scene_snapshot,
        rig_topology=rig_topology,
        deformation_binding=deformation_binding,
        source_provider=provider,
        source_native_id=source_native_id,
        scope=scope,
        include_animation=include_animation,
        include_materials=include_materials,
        initial_issues=capture_issues,
    )
    if output_path:
        _raise_if_cancelled(cancel_event)
        _emit_progress(progress_callback, 98, "Writing compressed TC scene package")
        result.save(output_path)
    _emit_progress(progress_callback, 100, "TC scene conversion complete")
    return result


def capture_maya_scene(
    port: int,
    *,
    source_native_id: str = "",
    scope: str = "scene",
    include_animation: bool = True,
    progress_callback: Any = None,
    cancel_event: Any = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Capture the three Maya packets needed for an offline conversion."""
    from tech_connector.bridges.maya.maya_bridge import MayaBridge

    bridge = MayaBridge()
    capture_started = time.perf_counter()
    _raise_if_cancelled(cancel_event)
    _emit_progress(progress_callback, 2, "Inventorying Maya render assets and references")
    selected = str(scope or "scene").lower() == "selection"
    targets = [str(source_native_id)] if source_native_id else []
    ok, payload = bridge.get_scene_snapshot(
        port=int(port),
        selected_only=selected and not targets,
        meshes_only=not bool(targets),
        target_native_ids=targets or None,
        include_geometry=False,
        include_cameras=True,
        include_faces=False,
        limit=5000,
        timeout=120.0,
        cancel_event=cancel_event,
    )
    if not ok or not isinstance(payload, dict):
        raise RuntimeError(f"Maya scene capture failed: {payload}")
    inventory = payload
    if not targets:
        targets = [
            str(item.get("native_id") or "")
            for item in inventory.get("objects") or []
            if isinstance(item, dict) and str(item.get("native_id") or "")
        ]
    mesh_targets = list(dict.fromkeys(targets))
    inventory_ms = (time.perf_counter() - capture_started) * 1000.0

    issues: list[dict[str, Any]] = []
    converted_objects: list[dict[str, Any]] = []
    geometry_timings: list[dict[str, Any]] = []
    for index, mesh_native_id in enumerate(mesh_targets):
        _raise_if_cancelled(cancel_event)
        phase_started = time.perf_counter()
        _emit_progress(
            progress_callback,
            5 + int(43 * index / max(1, len(mesh_targets))),
            f"Capturing geometry {index + 1}/{len(mesh_targets)}: {mesh_native_id.split('|')[-1]}",
        )
        ok, payload = bridge.get_scene_snapshot(
            port=int(port),
            target_native_ids=[mesh_native_id],
            include_geometry=True,
            include_cameras=False,
            include_faces=True,
            limit=8,
            max_vertices_per_object=2_000_000,
            max_faces_per_object=2_000_000,
            timeout=120.0,
            cancel_event=cancel_event,
        )
        if ok and isinstance(payload, dict) and payload.get("objects"):
            converted_objects.extend(
                dict(item) for item in payload.get("objects") or [] if isinstance(item, dict)
            )
        else:
            fallback = next(
                (
                    dict(item) for item in inventory.get("objects") or []
                    if isinstance(item, dict) and str(item.get("native_id") or "") == mesh_native_id
                ),
                None,
            )
            if fallback:
                converted_objects.append(fallback)
            issues.append(_issue(
                "warning", "geometry", mesh_native_id,
                f"Asset geometry capture failed: {payload}",
                "The asset keeps its inventory bounds and can be retried independently.",
            ))
        geometry_timings.append({
            "asset_id": mesh_native_id,
            "milliseconds": round((time.perf_counter() - phase_started) * 1000.0, 3),
            "ok": bool(ok),
        })
    snapshot = dict(inventory)
    snapshot["objects"] = converted_objects
    snapshot["capture_chunks"] = {
        "strategy": "one_render_asset_per_geometry_chunk",
        "geometry_chunks": len(mesh_targets),
        "rig_builder_seed_count": len(mesh_targets),
        "timings_ms": {"inventory": round(inventory_ms, 3), "geometry": geometry_timings},
    }

    topology: dict[str, Any] | None = None
    binding: dict[str, Any] | None = None
    if mesh_targets:
        _raise_if_cancelled(cancel_event)
        topology_cache_key = _maya_topology_cache_key(inventory, int(port), mesh_targets, include_animation)
        cached_topology = _cached_maya_topology(topology_cache_key)
        _emit_progress(
            progress_callback,
            52,
            "Reusing unchanged Maya rig topology" if cached_topology is not None else "Building the TC rig graph from semantic mesh roots",
        )
        phase_started = time.perf_counter()
        if cached_topology is not None:
            ok, payload = True, cached_topology
        else:
            ok, payload = bridge.get_rig_topology(
                port=int(port),
                target_native_ids=mesh_targets,
                include_attribute_values=bool(include_animation),
                timeout=180.0,
                cancel_event=cancel_event,
            )
            if ok and isinstance(payload, dict):
                _store_maya_topology(topology_cache_key, payload)
        snapshot["capture_chunks"]["timings_ms"]["rig_build"] = round(
            (time.perf_counter() - phase_started) * 1000.0, 3
        )
        snapshot["capture_chunks"]["rig_topology_cache_hit"] = cached_topology is not None
        if ok and isinstance(payload, dict):
            topology = payload
        else:
            issues.append(_issue("warning", "rig", "", f"Rig topology capture failed: {payload}", "Geometry remains convertible."))

        binding_chunks: list[dict[str, Any]] = []
        skin_timings: list[dict[str, Any]] = []
        for index, mesh_native_id in enumerate(mesh_targets):
            _raise_if_cancelled(cancel_event)
            phase_started = time.perf_counter()
            _emit_progress(
                progress_callback,
                64 + int(30 * index / max(1, len(mesh_targets))),
                f"Capturing skinning {index + 1}/{len(mesh_targets)}: {mesh_native_id.split('|')[-1]}",
            )
            ok, payload = bridge.get_deformation_binding(
                port=int(port),
                target_native_ids=[mesh_native_id],
                timeout=180.0,
                cancel_event=cancel_event,
            )
            if ok and isinstance(payload, dict):
                binding_chunks.append(payload)
            else:
                issues.append(_issue(
                    "warning", "skinning", mesh_native_id,
                    f"Skin capture failed: {payload}",
                    "This asset remains static and its skin chunk can be retried independently.",
                ))
            skin_timings.append({
                "asset_id": mesh_native_id,
                "milliseconds": round((time.perf_counter() - phase_started) * 1000.0, 3),
                "ok": bool(ok),
            })
        binding = _merge_deformation_binding_chunks(binding_chunks, provider_id=f"maya:{int(port)}")
        snapshot["capture_chunks"]["skinning_chunks"] = len(binding_chunks)
        snapshot["capture_chunks"]["timings_ms"]["skinning"] = skin_timings
    snapshot["capture_chunks"]["timings_ms"]["total"] = round(
        (time.perf_counter() - capture_started) * 1000.0, 3
    )
    return snapshot, topology, binding, issues


def _emit_progress(callback: Any, percent: int, description: str) -> None:
    if callable(callback):
        callback(max(0, min(100, int(percent))), str(description))


def _maya_topology_cache_key(
    inventory: dict[str, Any],
    port: int,
    mesh_targets: list[str],
    include_animation: bool,
) -> tuple[Any, ...] | None:
    if bool(inventory.get("scene_modified", True)):
        return None
    scene_path = Path(str(inventory.get("scene") or ""))
    if not scene_path.is_file():
        return None
    stat = scene_path.stat()
    return (
        int(port),
        int(inventory.get("process_id", 0) or 0),
        str(scene_path.resolve()).lower(),
        int(stat.st_size),
        int(stat.st_mtime_ns),
        int(inventory.get("scene_revision", 0) or 0),
        tuple(mesh_targets),
        bool(include_animation),
    )


def _cached_maya_topology(key: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if key is None:
        return None
    with _MAYA_TOPOLOGY_CACHE_LOCK:
        cached = _MAYA_TOPOLOGY_CACHE.get(key)
    return copy.deepcopy(cached) if cached is not None else None


def _store_maya_topology(key: tuple[Any, ...] | None, topology: dict[str, Any]) -> None:
    if key is None:
        return
    with _MAYA_TOPOLOGY_CACHE_LOCK:
        _MAYA_TOPOLOGY_CACHE[key] = copy.deepcopy(topology)
        while len(_MAYA_TOPOLOGY_CACHE) > _MAYA_TOPOLOGY_CACHE_LIMIT:
            _MAYA_TOPOLOGY_CACHE.pop(next(iter(_MAYA_TOPOLOGY_CACHE)))


def _raise_if_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("TC scene conversion canceled.")


def _merge_deformation_binding_chunks(chunks: list[dict[str, Any]], *, provider_id: str) -> dict[str, Any] | None:
    if not chunks:
        return None
    skeletons: dict[str, dict[str, Any]] = {}
    meshes: dict[str, dict[str, Any]] = {}
    merged = {
        key: value for key, value in chunks[0].items()
        if key not in {"skeletons", "meshes", "contract_errors", "provider_id", "schema"}
    }
    for chunk in chunks:
        for skeleton in chunk.get("skeletons") or []:
            native_id = str(skeleton.get("native_id") or "")
            if native_id and native_id not in skeletons:
                skeletons[native_id] = skeleton
        for mesh in chunk.get("meshes") or []:
            native_id = str(mesh.get("native_id") or "")
            if native_id:
                meshes[native_id] = mesh
    merged.update({"skeletons": list(skeletons.values()), "meshes": list(meshes.values())})
    return normalize_deformation_binding(merged, provider_id=provider_id)


def convert_scene_packets_to_tc(
    scene_snapshot: dict[str, Any],
    *,
    rig_topology: dict[str, Any] | None = None,
    deformation_binding: dict[str, Any] | None = None,
    source_provider: str = "maya",
    source_native_id: str = "",
    scope: str = "scene",
    include_animation: bool = True,
    include_materials: bool = True,
    initial_issues: list[dict[str, Any]] | None = None,
) -> TCSceneConversionResult:
    """Create an editable, self-contained TC document from provider packets."""
    if not isinstance(scene_snapshot, dict):
        raise TypeError("scene_snapshot must be a dictionary.")
    provider = str(source_provider or scene_snapshot.get("provider_id") or "maya").strip().lower().split(":", 1)[0]
    snapshot = _standalone_snapshot(scene_snapshot, provider, include_materials=include_materials)
    objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
    if not objects:
        raise ValueError("The source scene did not contain any convertible objects.")

    graph = EditableRigGraph()
    blobs: dict[str, bytes] = {
        EMBEDDED_SCENE_SNAPSHOT_BLOB: json.dumps(snapshot, separators=(",", ":"), sort_keys=True).encode("utf-8")
    }
    issues = list(initial_issues or [])
    normalized_topology: dict[str, Any] | None = None
    if rig_topology:
        normalized_topology = normalize_rig_topology(rig_topology, provider_id=provider)
        contract_errors = list(normalized_topology.get("contract_errors") or [])
        if contract_errors:
            raise ValueError("Invalid source rig topology: " + "; ".join(contract_errors[:8]))
        graph.merge_rig_topology(normalized_topology, provider_id=provider)

    normalized_binding: dict[str, Any] | None = None
    if deformation_binding:
        normalized_binding = normalize_deformation_binding(deformation_binding, provider_id=provider)
        contract_errors = list(normalized_binding.get("contract_errors") or [])
        if contract_errors:
            raise ValueError("Invalid source deformation binding: " + "; ".join(contract_errors[:8]))
        blobs.update(graph.merge_deformation_binding(normalized_binding, provider_id=provider))

    _promote_graph_to_native(graph, provider, issues)
    if include_animation and normalized_topology:
        _convert_animation_curves(graph, normalized_topology, provider, scene_snapshot)
    conversion_receipt = compile_graph_to_tc_native(graph, provider)

    scene_path = str(scene_snapshot.get("scene") or scene_snapshot.get("file") or "")
    scene_name = Path(scene_path).stem if scene_path else "Converted TC Scene"
    counts = _conversion_counts(snapshot, graph)
    report = {
        "schema": CONVERSION_SCHEMA,
        "source_provider": provider,
        "source_scene": scene_path,
        "source_native_id": str(source_native_id or ""),
        "scope": str(scope or "scene"),
        "status": "converted_with_warnings" if issues else "converted",
        "counts": counts,
        "issues": issues,
        "adapter_readiness": conversion_readiness(provider),
        "native_conversion_receipt": conversion_receipt,
        "engine_transfer": {
            "geometry": "embedded_polygon_mesh",
            "rig": "tc_native_runtime_graph",
            "skinning": "sparse_csr_f32_u32" if graph.skins else "none",
            "animation": "tc_animation_take" if graph.animation else "none",
            "runtime_authoring": runtime_authoring_contract(),
        },
        "build_chunks": _conversion_build_chunks(snapshot, graph),
    }
    graph.metadata.update({
        "conversion_schema": CONVERSION_SCHEMA,
        "source_provider": provider,
        "source_scene": scene_path,
        "converted_native": True,
    })
    document = FederatedSceneDocument(
        name=scene_name,
        sources=[{
            "provider": "tech_connector",
            "session_key": "tc_native_converted",
            "source_path": "",
            "reload_policy": "embedded",
            "snapshot_blob": EMBEDDED_SCENE_SNAPSHOT_BLOB,
            "origin": {"provider": provider, "source_path": scene_path, "native_id": str(source_native_id or "")},
        }],
        rig_graph=graph,
        timeline={
            "frame": int(float(scene_snapshot.get("current_time", 1) or 1)),
            "start": int(float(scene_snapshot.get("frame_start", 1) or 1)),
            "end": int(float(scene_snapshot.get("frame_end", 120) or 120)),
            "frame_rate": float(scene_snapshot.get("frame_rate", 24.0) or 24.0),
        },
        metadata={
            "tc_native_scene_snapshot_blob": EMBEDDED_SCENE_SNAPSHOT_BLOB,
            "conversion_report": report,
        },
    )
    return TCSceneConversionResult(document=document, blobs=blobs, report=report, scene_snapshot=snapshot)


def _standalone_snapshot(snapshot: dict[str, Any], provider: str, *, include_materials: bool) -> dict[str, Any]:
    result = _json_safe(copy.deepcopy(snapshot))
    source_provider_id = str(snapshot.get("provider_id") or provider)
    unit_linear = str(snapshot.get("unit_linear") or "") or None
    up_axis = str(snapshot.get("up_axis") or "") or None
    result["provider_id"] = "tech_connector"
    result["source_provider"] = source_provider_id
    result["source_scene"] = str(snapshot.get("scene") or snapshot.get("file") or "")
    result["unit_linear"] = "cm"
    result["up_axis"] = "y"
    result["forward_axis"] = "z"
    result["conversion_state"] = "tc_native"
    object_id_map: dict[str, str] = {}
    for obj in result.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        source_id = str(obj.get("native_id") or obj.get("id") or obj.get("name") or "object")
        tc_id = stable_tc_id("node", provider, source_id)
        object_id_map[source_id] = tc_id
        obj["source_ref"] = {
            **dict(obj.get("source_ref") or {}),
            "provider_id": source_provider_id,
            "native_id": source_id,
        }
        obj["native_id"] = tc_id
        obj["id"] = tc_id
        _canonicalize_point_field(obj, "translation", provider, unit_linear, up_axis)
        _canonicalize_point_field(obj, "position", provider, unit_linear, up_axis)
        if isinstance(obj.get("bbox"), (list, tuple)) and len(obj["bbox"]) == 6:
            obj["source_bbox"] = list(obj["bbox"])
            obj["bbox"] = list(provider_bbox_to_shared(provider, obj["bbox"], unit_linear, up_axis))
        geometry = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else {}
        if not geometry.get("vertices") and geometry.get("vertices_f32"):
            flat = list(geometry.pop("vertices_f32"))
            geometry["vertices"] = [flat[index:index + 3] for index in range(0, len(flat) - 2, 3)]
        if isinstance(geometry.get("vertices"), list):
            geometry["vertices"] = [
                list(provider_native_to_shared(provider, point, unit_linear, up_axis))
                for point in geometry["vertices"] if isinstance(point, (list, tuple)) and len(point) >= 3
            ]
        geometry.pop("vertex_encoding", None)
        if not include_materials:
            obj.pop("material", None)
            obj.pop("materials", None)
    for obj in result.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        for parent_key in ("parent_id", "parent_native_id"):
            parent_id = str(obj.get(parent_key) or "")
            if parent_id:
                obj[parent_key] = object_id_map.get(parent_id, stable_tc_id("node", provider, parent_id))
    for camera in result.get("cameras") or []:
        if not isinstance(camera, dict):
            continue
        source_id = str(camera.get("native_id") or camera.get("id") or camera.get("name") or "camera")
        camera["source_ref"] = {"provider_id": source_provider_id, "native_id": source_id}
        camera["native_id"] = stable_tc_id("camera", provider, source_id)
        camera["id"] = camera["native_id"]
        for key in ("translation", "position", "eye", "target", "up_target"):
            _canonicalize_point_field(camera, key, provider, unit_linear, up_axis)
    return result


def _canonicalize_point_field(
    payload: dict[str, Any], key: str, provider: str, unit_linear: str | None, up_axis: str | None
) -> None:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return
    payload[f"source_{key}"] = list(value)
    payload[key] = list(provider_native_to_shared(provider, value, unit_linear, up_axis))


def _promote_graph_to_native(graph: EditableRigGraph, provider: str, issues: list[dict[str, Any]]) -> None:
    collections = (graph.nodes, graph.connections, graph.joints, graph.skins, graph.constraints, graph.deformers)
    for collection in collections:
        for item in collection.values():
            item["ownership"] = "native"
            item["edit_policy"] = "full"
    unsupported_by_type: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        portable = bool(node.get("portable", False))
        node["evaluation_mode"] = "local" if portable else "source_proxy"
        source_ref = dict(node.get("source_ref") or {})
        source_ref["conversion_origin"] = provider
        node["source_ref"] = source_ref
        if not portable:
            source_type = str(node.get("source_type") or "Unknown")
            unsupported_by_type.setdefault(source_type, []).append(
                str(source_ref.get("native_id") or node.get("native_id") or node.get("id") or "")
            )
    for skin in graph.skins.values():
        skin["evaluation_mode"] = "gpu_local" if str(skin.get("deformation_mode")) == "linear_blend_skinning" else "local"
    for constraint in graph.constraints.values():
        constraint["evaluation_mode"] = "local" if str(constraint.get("type") or "") != "opaque" else "source_proxy"
    for source_type, source_ids in sorted(unsupported_by_type.items()):
        issue = _issue(
            "warning",
            "rig_node",
            source_ids[0] if len(source_ids) == 1 else "",
            f"{len(source_ids)} {source_type} node(s) have no native TC evaluator.",
            "They are retained as editable opaque source proxies and can be baked or replaced.",
        )
        issue["count"] = len(source_ids)
        issue["sample_source_ids"] = source_ids[:8]
        issues.append(issue)


def _convert_animation_curves(
    graph: EditableRigGraph,
    topology: dict[str, Any],
    provider: str,
    snapshot: dict[str, Any],
) -> None:
    curves: dict[str, dict[str, Any]] = {}
    connections = list(topology.get("connections") or [])
    for node in topology.get("nodes") or []:
        if str(node.get("node_type") or "") != "animation.curve":
            continue
        source_id = str(node.get("native_id") or "")
        keys = list((node.get("attributes") or {}).get("keys") or [])
        if not keys or str((node.get("attributes") or {}).get("input_domain") or "time") != "time":
            continue
        for connection in connections:
            if str(connection.get("source_node") or "") != source_id:
                continue
            target_native_id = str(connection.get("target_node") or "")
            target_id = f"{provider}::{target_native_id}"
            if target_id not in graph.nodes:
                continue
            attribute = str(connection.get("target_attribute") or "")
            curve_id = f"{target_id}.{attribute}"
            curves[curve_id] = {
                "node_id": target_id,
                "attribute": attribute,
                "source_curve": source_id,
                "pre_infinity": (node.get("attributes") or {}).get("pre_infinity"),
                "post_infinity": (node.get("attributes") or {}).get("post_infinity"),
                "weighted_tangents": bool((node.get("attributes") or {}).get("weighted_tangents", False)),
                "keys": [dict(key) for key in keys if isinstance(key, dict)],
            }
    if not curves:
        return
    take_id = "take_maya_base"
    graph.animation[take_id] = {
        "id": take_id,
        "type": "animation_take",
        "name": "Maya Base Animation",
        "start_frame": int(float(snapshot.get("frame_start", 1) or 1)),
        "end_frame": int(float(snapshot.get("frame_end", 120) or 120)),
        "frame_rate": float(snapshot.get("frame_rate", 24.0) or 24.0),
        "timecode_start": str(snapshot.get("timecode_start") or "00:00:00:00"),
        "active_layer": "BaseAnimation",
        "layers": {
            "BaseAnimation": {
                "name": "BaseAnimation",
                "weight": 1.0,
                "muted": False,
                "solo": False,
                "additive": False,
                "curves": curves,
            }
        },
        "source_provider": provider,
    }


def _conversion_counts(snapshot: dict[str, Any], graph: EditableRigGraph) -> dict[str, int]:
    objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
    return {
        "objects": len(objects),
        "meshes": sum(1 for item in objects if str(item.get("type") or "").lower() in {"mesh", "skeletal_mesh"}),
        "materials": sum(1 for item in objects if item.get("material") or item.get("materials")),
        "cameras": len(snapshot.get("cameras") or []) + sum(1 for item in objects if str(item.get("type") or "").lower() == "camera"),
        "rig_nodes": len(graph.nodes),
        "connections": len(graph.connections),
        "joints": len(graph.joints),
        "skins": len(graph.skins),
        "constraints": len(graph.constraints),
        "animation_takes": len(graph.animation),
    }


def _conversion_build_chunks(snapshot: dict[str, Any], graph: EditableRigGraph) -> dict[str, Any]:
    """Describe retryable asset chunks and the compact semantic rig-builder handoff."""
    objects = [item for item in snapshot.get("objects") or [] if isinstance(item, dict)]
    skins_by_mesh = {
        str((skin.get("source_ref") or {}).get("mesh_native_id") or ""): skin_id
        for skin_id, skin in graph.skins.items()
    }
    assets = []
    references: dict[str, dict[str, Any]] = {}
    for obj in objects:
        native_id = str(obj.get("native_id") or "")
        source_id = str((obj.get("source_ref") or {}).get("native_id") or native_id)
        reference = dict(obj.get("reference") or {}) if isinstance(obj.get("reference"), dict) else {}
        reference_path = str(reference.get("source_path") or "")
        assets.append({
            "asset_id": native_id,
            "source_id": source_id,
            "reference_source": reference_path,
            "chunks": {
                "geometry": {"source_id": source_id, "tc_id": native_id, "representation": str((obj.get("geometry") or {}).get("representation") or "bounds")},
                "material": {"source_id": str((obj.get("material") or {}).get("source_material_id") or "")},
                "skinning": {"skin_id": skins_by_mesh.get(source_id, ""), "required": source_id in skins_by_mesh},
            },
        })
        if reference_path:
            entry = references.setdefault(reference_path, {
                "source_path": reference_path,
                "reference_node": str(reference.get("reference_node") or ""),
                "namespace": str(reference.get("namespace") or ""),
                "asset_ids": [],
                "conversion_order": "child_tcscene_before_parent_reference_replacement",
                "target": "separate_tcscene",
            })
            entry["asset_ids"].append(native_id)
    return {
        "policy": "one asset per independently retryable chunk set",
        "assets": assets,
        "skeleton_chunks": [
            {"skeleton_id": str((joint.get("source_ref") or {}).get("native_id") or joint_id), "joint_id": joint_id}
            for joint_id, joint in graph.joints.items()
            if not str(joint.get("parent_id") or "")
        ],
        "rig_build": {
            "builder": "tc_native_rig_create",
            "inputs": {
                "node_ids": list(graph.nodes),
                "connection_ids": list(graph.connections),
                "constraint_ids": list(graph.constraints),
                "skeleton_root_ids": [joint_id for joint_id, joint in graph.joints.items() if not str(joint.get("parent_id") or "")],
                "skin_ids": list(graph.skins),
            },
            "parameter_policy": "resolve node parameters from chunk IDs; do not serialize every rig parameter into one command",
        },
        "references": list(references.values()),
        "parent_replacement_policy": (
            "convert each referenced source scene to a separate tcscene, load-validate it, then replace the parent reference with a tcscene reference"
        ),
        "reference_overrides": "store parent-local edits as a stable-ID override layer; never mutate or duplicate the child tcscene",
    }


def _issue(severity: str, category: str, source_id: str, message: str, fallback: str) -> dict[str, Any]:
    return {
        "severity": str(severity),
        "category": str(category),
        "source_id": str(source_id),
        "message": str(message),
        "fallback": str(fallback),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, array.array)):
        return [_json_safe(item) for item in value]
    if isinstance(value, memoryview):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, bytes):
        return list(value)
    return value


