"""Evidence-gated synthesis and validation of generic Blueprint graph specs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


REFERENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "reference"
    / "unreal_blueprint_atomic_actions.json"
)


def load_verified_pin_signatures(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Return only signatures backed by a clean live compile and probe reset."""

    source = Path(path) if path else REFERENCE_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return {
        str(action): dict(signature)
        for action, signature in dict(payload.get("pin_signatures") or {}).items()
        if str(signature.get("compile_status") or "") == "BS_UP_TO_DATE"
        and signature.get("probe_reset") is True
        and signature.get("original_dirty_unchanged") is True
    }


def _pin_map(signature: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        str(pin.get("name") or ""): {
            "direction": str(pin.get("direction") or "").lower(),
            "type": str(pin.get("type") or ""),
        }
        for pin in signature.get("pins") or []
        if pin.get("name")
    }


def _types_compatible(source_type: str, target_type: str) -> bool:
    if not source_type or not target_type:
        return False
    if "wildcard" in {source_type.lower(), target_type.lower()}:
        return True
    return source_type == target_type


def validate_graph_spec_against_pin_evidence(
    graph_spec: dict[str, Any],
    *,
    pin_signatures: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fail closed unless every node, value, and link is supported by live pin evidence."""

    signatures = dict(pin_signatures or load_verified_pin_signatures())
    nodes = list((graph_spec or {}).get("nodes") or [])
    links = list((graph_spec or {}).get("links") or [])
    errors: list[dict[str, Any]] = []
    node_by_id: dict[str, dict[str, Any]] = {}
    pins_by_id: dict[str, dict[str, dict[str, str]]] = {}

    if not nodes:
        errors.append({"code": "nodes_required", "message": "At least one node is required."})
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or "").strip()
        action = str(node.get("palette_action") or "").strip()
        if not node_id or not action:
            errors.append({"code": "invalid_node", "index": index, "message": "Node id and palette_action are required."})
            continue
        if node_id in node_by_id:
            errors.append({"code": "duplicate_node_id", "node": node_id})
            continue
        node_by_id[node_id] = node
        signature = signatures.get(action)
        if not signature:
            errors.append({"code": "missing_pin_evidence", "node": node_id, "palette_action": action})
            continue
        pins = _pin_map(signature)
        pins_by_id[node_id] = pins
        for pin_name in dict(node.get("pin_values") or {}):
            pin = pins.get(str(pin_name))
            if not pin:
                errors.append({"code": "unknown_value_pin", "node": node_id, "pin": pin_name})
            elif pin["direction"] != "input" or pin["type"] == "exec":
                errors.append({"code": "invalid_value_pin", "node": node_id, "pin": pin_name})

    for index, link in enumerate(links):
        source_id = str(link.get("source_node") or "")
        target_id = str(link.get("target_node") or "")
        source_name = str(link.get("source_pin") or "")
        target_name = str(link.get("target_pin") or "")
        source = pins_by_id.get(source_id, {}).get(source_name)
        target = pins_by_id.get(target_id, {}).get(target_name)
        if source is None:
            errors.append({"code": "unknown_source_pin", "index": index, "node": source_id, "pin": source_name})
            continue
        if target is None:
            errors.append({"code": "unknown_target_pin", "index": index, "node": target_id, "pin": target_name})
            continue
        if source["direction"] != "output" or target["direction"] != "input":
            errors.append({"code": "invalid_link_direction", "index": index, "source": source, "target": target})
        if not _types_compatible(source["type"], target["type"]):
            errors.append({"code": "incompatible_pin_types", "index": index, "source_type": source["type"], "target_type": target["type"]})

    return {
        "ok": not errors,
        "status": "validated" if not errors else "blocked",
        "graph_spec": graph_spec,
        "errors": errors,
        "verified_actions": sorted({str(node.get("palette_action") or "") for node in nodes if str(node.get("palette_action") or "") in signatures}),
        "mutation_allowed": False,
        "next_gate": "implementation plan approval" if not errors else "repair graph spec or gather missing live pin evidence",
    }


def build_graph_spec_prompt(
    semantic_operations: Iterable[dict[str, Any]],
    *,
    available_actions: Iterable[str],
    pin_signatures: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a bounded model request; this function performs no model call or mutation."""

    signatures = dict(pin_signatures or load_verified_pin_signatures())
    allowed = [str(action) for action in available_actions if str(action) in signatures]
    return {
        "system": (
            "Compose an Unreal Blueprint graph specification from atomic semantic operations. "
            "Use only the supplied exact palette_action values and exact pin names. Return JSON only. "
            "Do not claim compilation, saving, or runtime success. Leave any unavailable operation unresolved."
        ),
        "input": {
            "semantic_operations": [dict(value) for value in semantic_operations],
            "allowed_actions": allowed,
            "pin_signatures": {action: signatures[action] for action in allowed},
            "output_schema": {
                "nodes": [{"id": "string", "palette_action": "exact allowed action", "pin_values": {}}],
                "links": [{"source_node": "id", "source_pin": "output pin", "target_node": "id", "target_pin": "input pin"}],
                "unresolved_operations": ["semantic operation key"],
            },
        },
        "mutation_allowed": False,
    }
