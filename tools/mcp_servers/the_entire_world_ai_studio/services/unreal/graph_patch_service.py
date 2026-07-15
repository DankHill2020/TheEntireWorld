"""Unreal graph patch service v1.

This module turns a rewrite idea into a structured, previewable, validatable,
and executable patch object. It is conservative by design: it will only attempt
live apply when preflight passes and the requested operations are supported by
current Unreal Python graph hooks.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _pin_direction(pin: dict[str, Any]) -> str:
    return _safe_str((pin or {}).get("direction")).lower()


def _property_names(node: dict[str, Any]) -> set[str]:
    props = (node or {}).get("properties") or []
    if isinstance(props, dict):
        return {str(k) for k in props.keys()}
    if isinstance(props, list):
        out: set[str] = set()
        for item in props:
            if isinstance(item, dict) and item.get("name"):
                out.add(str(item.get("name")))
            elif item:
                out.add(str(item))
        return out
    return set()


def _class_matches(requested: str, actual: str) -> bool:
    requested = _safe_str(requested).lower().replace(" ", "")
    actual = _safe_str(actual).lower().replace(" ", "")
    if not requested or not actual:
        return False
    if requested in actual or actual in requested:
        return True
    aliases = {
        "development|printstring": ("printstring", "print", "k2node_callfunction"),
        "k2node_knot": ("k2node_knot", "reroute", "knot"),
    }
    return any(alias in actual for alias in aliases.get(requested, ()))


def _node_has_value(node: dict[str, Any], value: Any) -> bool:
    if value is None:
        return True
    expected = _safe_str(value)
    if not expected:
        return True
    return expected in str(node)


def _validate_added_nodes_in_snapshot(
    patch: GraphPatch,
    graph_snapshot_after: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(graph_snapshot_after, dict):
        return ["Post-apply graph snapshot was unavailable; added nodes could not be verified."]

    graph_nodes: list[dict[str, Any]] = []
    if str(graph_snapshot_after.get("name") or "") == patch.target_graph and isinstance(graph_snapshot_after.get("nodes"), list):
        graph_nodes.extend(node for node in (graph_snapshot_after.get("nodes") or []) if isinstance(node, dict))
    else:
        for graph in graph_snapshot_after.get("graphs") or []:
            if not isinstance(graph, dict) or str(graph.get("name") or "") != patch.target_graph:
                continue
            graph_nodes.extend(node for node in (graph.get("nodes") or []) if isinstance(node, dict))

    if not graph_nodes:
        return [f"Post-apply graph snapshot did not include nodes for {patch.target_graph}."]

    errors: list[str] = []
    for op in patch.operations:
        if op.op != "add_node":
            continue
        requested_name = _safe_str(op.node)
        requested_class = _safe_str(op.node_class)
        candidates: list[dict[str, Any]] = []
        for node in graph_nodes:
            node_name = _safe_str(node.get("name"))
            node_class = _safe_str(node.get("class"))
            if requested_name and requested_name == node_name:
                candidates.append(node)
            elif requested_class and _class_matches(requested_class, node_class):
                candidates.append(node)
        if not candidates:
            errors.append(
                f"Added node could not be verified in post-apply snapshot: {requested_name or requested_class or 'unnamed add_node'}."
            )
            continue
        if op.property_value is not None and not any(_node_has_value(node, op.property_value) for node in candidates):
            errors.append(
                f"Added node value could not be verified in post-apply snapshot: {op.property_name or 'value'}={op.property_value}."
            )
    return errors


GRAPH_PATCH_OPS = {
    "add_node",
    "remove_node",
    "set_property",
    "connect_pins",
    "disconnect_pins",
}


@dataclass
class GraphPatchOperation:
    op: str
    graph: str
    node: str = ""
    node_class: str = ""
    from_node: str = ""
    from_pin: str = ""
    to_node: str = ""
    to_pin: str = ""
    property_name: str = ""
    property_value: Any = None
    reason: str = ""


@dataclass
class GraphPatch:
    patch_id: str
    target_asset: str
    target_graph: str
    operations: list[GraphPatchOperation] = field(default_factory=list)
    compile_expectations: list[str] = field(default_factory=list)
    risk_level: str = "high"
    requires_confirmation: bool = True
    backup_strategy: str = "prototype_or_backup_before_apply"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    graph_exists: bool | str = "unknown"
    matched_nodes: list[str] = field(default_factory=list)
    matched_pins: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


@dataclass
class PatchPreview:
    summary: str
    operation_count: int
    node_additions: list[dict[str, Any]]
    node_removals: list[dict[str, Any]]
    property_changes: list[dict[str, Any]]
    pin_links_to_create: list[dict[str, Any]]
    pin_links_to_remove: list[dict[str, Any]]
    compile_expectations: list[str]
    risk_level: str
    visible_state: str = "CHANGE_PLANNED"
    next_state: str = "AWAITING_APPROVAL"
    open_focus_operations: list[str] = field(default_factory=list)
    focus_targets: list[dict[str, str]] = field(default_factory=list)
    layout_requirements: list[str] = field(default_factory=list)
    post_apply_validation: list[str] = field(default_factory=list)
    progress_stages: list[dict[str, Any]] = field(default_factory=list)
    threading_contract: dict[str, Any] = field(default_factory=dict)
    edit_intelligence: dict[str, Any] = field(default_factory=dict)
    preflight_checks: list[str] = field(default_factory=list)
    insertion_strategy: list[str] = field(default_factory=list)
    troubleshooting_path: list[str] = field(default_factory=list)
    repair_strategies: list[str] = field(default_factory=list)


@dataclass
class RollbackManifest:
    patch_id: str
    target_asset: str
    backup_strategy: str
    rollback_token: str
    backup_asset: str = ""
    steps: list[str] = field(default_factory=list)


@dataclass
class PatchExecutionResult:
    ok: bool
    mode: str
    patch: dict[str, Any]
    preflight: dict[str, Any]
    preview: dict[str, Any]
    rollback: dict[str, Any]
    applied: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    apply_result: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    request: dict[str, Any] = field(default_factory=dict)


def build_patch(
    target_asset: str,
    target_graph: str,
    operations: list[dict[str, Any]] | None = None,
    *,
    compile_expectations: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> GraphPatch:
    ops: list[GraphPatchOperation] = []
    for item in operations or []:
        op_name = str(item.get("op") or "")
        if op_name not in GRAPH_PATCH_OPS:
            raise ValueError(f"Unsupported graph patch operation: {op_name}")
        ops.append(GraphPatchOperation(**item))
    return GraphPatch(
        patch_id=str(uuid.uuid4()),
        target_asset=str(target_asset or ""),
        target_graph=str(target_graph or ""),
        operations=ops,
        compile_expectations=list(
            compile_expectations or ["Blueprint compiles cleanly"]
        ),
        metadata=dict(metadata or {}),
    )


def build_preview(patch: GraphPatch) -> PatchPreview:
    from services.unreal.semantic_graph_service import (
        GRAPH_LAYOUT_CONTRACT,
        graph_edit_progress_events,
        graph_edit_threading_contract,
    )

    node_additions = [asdict(op) for op in patch.operations if op.op == "add_node"]
    node_removals = [asdict(op) for op in patch.operations if op.op == "remove_node"]
    property_changes = [
        asdict(op) for op in patch.operations if op.op == "set_property"
    ]
    pin_links_to_create = [
        asdict(op) for op in patch.operations if op.op == "connect_pins"
    ]
    pin_links_to_remove = [
        asdict(op) for op in patch.operations if op.op == "disconnect_pins"
    ]
    summary = (
        f"Patch {patch.patch_id[:8]} targets {patch.target_asset or 'unknown asset'} / {patch.target_graph or 'unknown graph'} "
        f"with {len(patch.operations)} operation(s)."
    )
    edit_intelligence = dict((patch.metadata or {}).get("edit_intelligence") or {})
    return PatchPreview(
        summary=summary,
        operation_count=len(patch.operations),
        node_additions=node_additions,
        node_removals=node_removals,
        property_changes=property_changes,
        pin_links_to_create=pin_links_to_create,
        pin_links_to_remove=pin_links_to_remove,
        compile_expectations=list(patch.compile_expectations),
        risk_level=patch.risk_level,
        open_focus_operations=list(
            (patch.metadata or {}).get("open_focus_operations")
            or ["navigation.open_asset", "blueprint.open_graph", "blueprint.focus_graph_item", "focus_or_select_planned_insertion_area_when_supported"]
        ),
        focus_targets=list((patch.metadata or {}).get("focus_targets") or []),
        layout_requirements=list(
            (patch.metadata or {}).get("layout_contract")
            or GRAPH_LAYOUT_CONTRACT
        ),
        post_apply_validation=list(
            (patch.metadata or {}).get("post_apply_validation")
            or [
                "Compile modified asset and capture warnings/errors",
                "Verify required execution and data pins",
                "Verify no orphaned nodes, invalid references, or accidental loops",
                "Verify graph layout readability",
                "Report exact graph diff and rollback token",
            ]
        ),
        progress_stages=list(
            (patch.metadata or {}).get("progress_stages")
            or graph_edit_progress_events()
        ),
        threading_contract=dict(
            (patch.metadata or {}).get("threading_contract")
            or graph_edit_threading_contract()
        ),
        edit_intelligence=edit_intelligence,
        preflight_checks=list(
            (patch.metadata or {}).get("preflight_checks")
            or edit_intelligence.get("preflight_checks")
            or []
        ),
        insertion_strategy=list(
            (patch.metadata or {}).get("insertion_strategy")
            or edit_intelligence.get("insertion_strategy")
            or []
        ),
        troubleshooting_path=list(
            (patch.metadata or {}).get("troubleshooting_path")
            or edit_intelligence.get("troubleshooting_path")
            or []
        ),
        repair_strategies=list(
            (patch.metadata or {}).get("repair_strategies")
            or edit_intelligence.get("repair_strategies")
            or []
        ),
    )


def build_rollback_manifest(
    patch: GraphPatch, backup_asset: str = ""
) -> RollbackManifest:
    token = f"rollback:{patch.patch_id}"
    return RollbackManifest(
        patch_id=patch.patch_id,
        target_asset=patch.target_asset,
        backup_strategy=patch.backup_strategy,
        rollback_token=token,
        backup_asset=backup_asset,
        steps=[
            "Restore prototype/backup asset created before apply.",
            "Re-open target Blueprint and recompile.",
            "Validate references after restore.",
        ],
    )


def preflight_validate(
    patch: GraphPatch, graph_snapshot: dict[str, Any] | None = None
) -> PreflightResult:
    graph_snapshot = graph_snapshot or {}
    errors: list[str] = []
    warnings: list[str] = []
    unknowns: list[str] = []
    matched_nodes: list[str] = []
    matched_pins: list[str] = []

    if not patch.target_asset:
        errors.append("target_asset is required")
    if not patch.target_graph:
        errors.append("target_graph is required")

    graphs = [g for g in (graph_snapshot.get("graphs") or []) if isinstance(g, dict)]
    graph_names = [str(g.get("name")) for g in graphs]
    graph_exists: bool | str = (
        patch.target_graph in graph_names if graph_names else "unknown"
    )
    if graph_exists is False:
        errors.append(f"Target graph not found: {patch.target_graph}")
    elif graph_exists == "unknown":
        warnings.append("Graph existence could not be verified from snapshot")

    node_lookup: dict[str, dict[str, Any]] = {}
    pin_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for graph in graphs:
        if str(graph.get("name")) != patch.target_graph:
            continue
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_name = str(node.get("name") or "")
            if node_name:
                node_lookup[node_name] = node
            for pin in node.get("pins") or []:
                if isinstance(pin, dict):
                    pin_lookup[(node_name, str(pin.get("name") or ""))] = pin

    for op in patch.operations:
        if op.op == "add_node":
            if not op.node_class:
                errors.append("add_node requires node_class")
            if not op.node:
                unknowns.append(
                    "add_node has no explicit node name; Unreal may assign one"
                )
            class_ref = _safe_str(op.node_class)
            if (
                class_ref
                and "." not in class_ref
                and not class_ref.startswith("K2Node_")
                and class_ref not in {"Development|PrintString", "Development|Print String"}
            ):
                warnings.append(
                    f"add_node node_class may be too ambiguous for live creation: {class_ref}"
                )
            if class_ref not in {"Development|PrintString", "Development|Print String"}:
                warnings.append(
                    "add_node live apply remains limited; unsupported node classes are blocked on the Unreal side"
                )
        elif op.op == "remove_node":
            if not op.node:
                errors.append("remove_node requires node")
            elif node_lookup and op.node not in node_lookup:
                errors.append(f"Node not found for removal: {op.node}")
            else:
                matched_nodes.append(op.node)
        elif op.op == "set_property":
            if not op.node or not op.property_name:
                errors.append("set_property requires node and property_name")
            elif node_lookup and op.node not in node_lookup:
                errors.append(f"Node not found for property change: {op.node}")
            else:
                matched_nodes.append(op.node)
                if node_lookup:
                    props = _property_names(node_lookup.get(op.node) or {})
                    if props:
                        if op.property_name not in props:
                            errors.append(
                                f"Property not found on node {op.node}: {op.property_name}"
                            )
                    else:
                        unknowns.append(
                            f"Property existence could not be verified for {op.node}.{op.property_name}"
                        )
        elif op.op in {"connect_pins", "disconnect_pins"}:
            required = [op.from_node, op.from_pin, op.to_node, op.to_pin]
            if not all(required):
                errors.append(f"{op.op} requires from_node/from_pin/to_node/to_pin")
            else:
                if pin_lookup:
                    src_pin = pin_lookup.get((op.from_node, op.from_pin))
                    dst_pin = pin_lookup.get((op.to_node, op.to_pin))
                    if not src_pin:
                        errors.append(
                            f"Source pin not found: {op.from_node}.{op.from_pin}"
                        )
                    else:
                        matched_pins.append(f"{op.from_node}.{op.from_pin}")
                    if not dst_pin:
                        errors.append(f"Target pin not found: {op.to_node}.{op.to_pin}")
                    else:
                        matched_pins.append(f"{op.to_node}.{op.to_pin}")
                    if src_pin and dst_pin:
                        src_dir = _pin_direction(src_pin)
                        dst_dir = _pin_direction(dst_pin)
                        if src_dir and dst_dir and src_dir == dst_dir:
                            errors.append(
                                f"Pin directions look incompatible: {op.from_node}.{op.from_pin} ({src_dir}) -> {op.to_node}.{op.to_pin} ({dst_dir})"
                            )
                        elif not src_dir or not dst_dir:
                            unknowns.append(
                                f"Pin direction could not be verified for {op.from_node}.{op.from_pin} -> {op.to_node}.{op.to_pin}"
                            )
                else:
                    warnings.append("Pin existence could not be verified from snapshot")
                if op.from_node == op.to_node and op.from_pin == op.to_pin:
                    errors.append("Cannot connect/disconnect a pin to itself")

    return PreflightResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        graph_exists=graph_exists,
        matched_nodes=matched_nodes,
        matched_pins=matched_pins,
        unknowns=unknowns,
    )


def execute_patch(
    patch: GraphPatch,
    *,
    graph_snapshot: dict[str, Any] | None = None,
    allow_apply: bool = False,
    bridge: Any = None,
) -> PatchExecutionResult:
    preview = build_preview(patch)
    preflight = preflight_validate(patch, graph_snapshot=graph_snapshot)
    rollback = build_rollback_manifest(patch)
    request_meta = {
        "target_asset": patch.target_asset,
        "target_graph": patch.target_graph,
        "operation_count": len(patch.operations),
        "allow_apply": bool(allow_apply),
        "visible_lifecycle": [
            "REQUEST_RECEIVED",
            "CONTEXT_GATHERING",
            "GRAPH_ANALYZED",
            "CHANGE_PLANNED",
            "AWAITING_APPROVAL" if not allow_apply else "ASSET_OPENED",
        ],
    }

    if not allow_apply:
        return PatchExecutionResult(
            ok=preflight.ok,
            mode="plan_only",
            patch=asdict(patch),
            preflight=asdict(preflight),
            preview=asdict(preview),
            rollback=asdict(rollback),
            applied=False,
            warnings=["Patch execution disabled; returning validated plan only."],
            request=request_meta,
        )

    if not preflight.ok:
        return PatchExecutionResult(
            ok=False,
            mode="blocked",
            patch=asdict(patch),
            preflight=asdict(preflight),
            preview=asdict(preview),
            rollback=asdict(rollback),
            applied=False,
            errors=list(preflight.errors),
            warnings=list(preflight.warnings) + list(preflight.unknowns),
            request=request_meta,
        )

    if bridge is None:
        return PatchExecutionResult(
            ok=False,
            mode="blocked",
            patch=asdict(patch),
            preflight=asdict(preflight),
            preview=asdict(preview),
            rollback=asdict(rollback),
            applied=False,
            errors=["Unreal bridge is required for live apply"],
            warnings=list(preflight.warnings) + list(preflight.unknowns),
            request=request_meta,
        )

    backup_result = bridge.backup_blueprint_asset(patch.target_asset)
    backup_data = backup_result.get("data") if isinstance(backup_result, dict) else {}
    backup_asset = (
        backup_data.get("backup_asset") if isinstance(backup_data, dict) else ""
    )
    rollback = build_rollback_manifest(patch, backup_asset=backup_asset)
    if not backup_result.get("ok"):
        return PatchExecutionResult(
            ok=False,
            mode="blocked",
            patch=asdict(patch),
            preflight=asdict(preflight),
            preview=asdict(preview),
            rollback=asdict(rollback),
            applied=False,
            errors=[backup_result.get("error") or "Backup failed before apply"],
            warnings=list(preflight.warnings) + list(preflight.unknowns),
            request=request_meta,
        )

    apply_result = bridge.apply_graph_patch(asdict(patch))
    apply_data = apply_result.get("data") if isinstance(apply_result, dict) else {}
    errors = list(preflight.errors)
    warnings = list(preflight.warnings)
    if isinstance(apply_data, dict):
        errors.extend(str(x) for x in (apply_data.get("errors") or []))
        warnings.extend(str(x) for x in (apply_data.get("warnings") or []))

    validation = {
        "compile_expected": list(patch.compile_expectations),
        "backup_asset": backup_asset,
        "compile_ok": bool(apply_data.get("compile_ok"))
        if isinstance(apply_data, dict)
        else False,
        "compile_errors": list(apply_data.get("compile_errors") or [])
        if isinstance(apply_data, dict)
        else [],
        "validation_errors": list(apply_data.get("validation_errors") or [])
        if isinstance(apply_data, dict)
        else [],
        "graph_snapshot_after": apply_data.get("graph_snapshot_after")
        if isinstance(apply_data, dict)
        else None,
    }
    validation_errors = _validate_added_nodes_in_snapshot(
        patch,
        validation["graph_snapshot_after"] if isinstance(validation, dict) else None,
    )
    validation["validation_errors"].extend(validation_errors)

    applied = bool(isinstance(apply_data, dict) and apply_data.get("applied"))
    partial = bool(isinstance(apply_data, dict) and apply_data.get("partial"))
    if not applied:
        validation["validation_errors"].append("No requested graph operations were applied.")
    ok = (
        bool(apply_result.get("ok"))
        and applied
        and not errors
        and not validation["compile_errors"]
        and not validation["validation_errors"]
    )
    return PatchExecutionResult(
        ok=ok,
        mode="applied" if applied and not partial else "apply_partial",
        patch=asdict(patch),
        preflight=asdict(preflight),
        preview=asdict(preview),
        rollback=asdict(rollback),
        applied=applied,
        errors=errors,
        warnings=warnings + list(preflight.unknowns),
        apply_result=apply_data if isinstance(apply_data, dict) else {},
        validation=validation,
        request=request_meta,
    )
