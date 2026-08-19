"""Host-neutral command mutations for an OpenUSD composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tech_connector.game_engine.scene.usd_composition_service import (
    UsdComposition,
    UsdCompositionResult,
    UsdLayerSpec,
    UsdPayloadRule,
    UsdPropertyOverride,
    UsdVariantSelection,
)


USD_COMPOSITION_COMMANDS = frozenset({
    "scene.compose_usd",
    "scene.inspect_usd_composition",
    "scene.set_usd_variant",
    "scene.set_usd_payload",
    "scene.set_usd_override",
})


@dataclass(frozen=True)
class UsdCompositionCommandOutcome:
    composition: UsdComposition
    response: dict[str, Any]
    requires_compose: bool = False
    output_path: str = ""


def apply_usd_composition_command(
    command: str,
    payload: dict[str, Any] | None = None,
    *,
    composition: UsdComposition | None = None,
    result: UsdCompositionResult | None = None,
) -> UsdCompositionCommandOutcome:
    """Apply one adaptive command without launching a compositor or touching Qt."""
    command = str(command)
    payload = dict(payload or {})
    if command not in USD_COMPOSITION_COMMANDS:
        raise KeyError(f"Unknown OpenUSD composition command: {command}")

    if command == "scene.compose_usd":
        current = _composition_from_payload(payload, composition)
        output_path = _output_path(payload, current, result)
        return UsdCompositionCommandOutcome(
            current,
            {
                "message": f"Composing {len(current.layers)} OpenUSD layer(s).",
                "composition": current.to_dict(),
                "output_path": output_path,
            },
            requires_compose=True,
            output_path=output_path,
        )

    current = _require_composition(composition)
    if command == "scene.inspect_usd_composition":
        manifest = dict(result.manifest) if result is not None else {}
        changes = current.source_changes()
        return UsdCompositionCommandOutcome(current, {
            "message": (
                f"OpenUSD composition has {len(current.layers)} layer(s), "
                f"{len(current.variants)} variant selection(s), and "
                f"{int(manifest.get('prim_count', 0) or 0)} composed prim(s)."
            ),
            "composition": current.to_dict(),
            "source_changes": changes,
            "changed_source_count": sum(bool(item.get("changed")) for item in changes),
            "output_path": str(getattr(result, "output_path", "") or ""),
            "manifest": manifest,
        })

    if command == "scene.set_usd_variant":
        prim_path = _required_text(payload, "prim_path")
        variant_set = _required_text(payload, "variant_set")
        selection = str(payload.get("selection") or "").strip()
        current.variants = [
            item for item in current.variants
            if (item.prim_path, item.variant_set) != (prim_path, variant_set)
        ]
        if not _is_remove(payload):
            if not selection:
                raise ValueError("selection is required when setting a USD variant.")
            current.variants.append(UsdVariantSelection(prim_path, variant_set, selection))
        message = f"Removed {variant_set} selection on {prim_path}." if _is_remove(payload) else f"Set {prim_path} {variant_set} to {selection}."

    elif command == "scene.set_usd_payload":
        prim_path = _required_text(payload, "prim_path")
        current.payload_rules = [item for item in current.payload_rules if item.prim_path != prim_path]
        if not _is_remove(payload):
            current.payload_rules.append(UsdPayloadRule(prim_path, loaded=bool(payload.get("loaded", True))))
        state = "default" if _is_remove(payload) else ("loaded" if bool(payload.get("loaded", True)) else "unloaded")
        message = f"Set {prim_path} payload policy to {state}."

    else:
        prim_path = _required_text(payload, "prim_path")
        property_name = _required_text(payload, "property_name")
        time_code = payload.get("time_code")
        current.overrides = [
            item for item in current.overrides
            if not (
                item.prim_path == prim_path
                and item.property_name == property_name
                and item.time_code == time_code
            )
        ]
        if not _is_remove(payload):
            if "value" not in payload:
                raise ValueError("value is required when setting a USD property override.")
            current.overrides.append(UsdPropertyOverride(
                prim_path=prim_path,
                property_name=property_name,
                value=payload["value"],
                value_type=str(payload.get("value_type") or "string"),
                time_code=float(time_code) if time_code is not None else None,
            ))
        message = f"Removed {property_name} override on {prim_path}." if _is_remove(payload) else f"Set {property_name} override on {prim_path}."

    errors = current.validate()
    if errors:
        raise ValueError("Invalid USD composition: " + "; ".join(errors))
    output_path = _output_path(payload, current, result)
    return UsdCompositionCommandOutcome(
        current,
        {"message": message, "composition": current.to_dict(), "output_path": output_path},
        requires_compose=True,
        output_path=output_path,
    )


def _composition_from_payload(payload: dict[str, Any], existing: UsdComposition | None) -> UsdComposition:
    raw_layers = payload.get("layers")
    if raw_layers is None:
        if existing is None:
            raise ValueError("layers is required to compose an OpenUSD stage.")
        current = UsdComposition.from_dict(existing.to_dict())
    else:
        if not isinstance(raw_layers, (list, tuple)) or not raw_layers:
            raise ValueError("layers must contain at least one OpenUSD source path.")
        layers = []
        for index, item in enumerate(raw_layers):
            if isinstance(item, str):
                layers.append(UsdLayerSpec(item, role="strongest_override" if index == 0 else "source"))
            elif isinstance(item, dict):
                layers.append(UsdLayerSpec(**dict(item)))
            else:
                raise TypeError(f"layers[{index}] must be a path or layer mapping.")
        current = UsdComposition(
            layers=layers,
            variants=[UsdVariantSelection(**dict(item)) for item in payload.get("variants") or []],
            payload_rules=[UsdPayloadRule(**dict(item)) for item in payload.get("payload_rules") or []],
            overrides=[UsdPropertyOverride(**dict(item)) for item in payload.get("overrides") or []],
            load_policy=str(payload.get("load_policy") or "all"),
            flatten=bool(payload.get("flatten", False)),
            metadata=dict(payload.get("metadata") or {}),
        )
    errors = current.validate()
    if errors:
        raise ValueError("Invalid USD composition: " + "; ".join(errors))
    return current


def _output_path(
    payload: dict[str, Any],
    composition: UsdComposition,
    result: UsdCompositionResult | None,
) -> str:
    requested = str(payload.get("output_path") or "").strip()
    if requested:
        return str(Path(requested).expanduser().resolve())
    previous = str(getattr(result, "output_path", "") or "").strip()
    if previous:
        return previous
    source = Path(composition.layers[0].path).expanduser().resolve()
    return str(source.with_name(source.stem + "_composed.usda"))


def _require_composition(composition: UsdComposition | None) -> UsdComposition:
    if composition is None:
        raise ValueError("No OpenUSD composition is attached to the current scene.")
    return UsdComposition.from_dict(composition.to_dict())


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def _is_remove(payload: dict[str, Any]) -> bool:
    return bool(payload.get("remove", False)) or str(payload.get("action") or "").lower() == "remove"


__all__ = ["USD_COMPOSITION_COMMANDS", "UsdCompositionCommandOutcome", "apply_usd_composition_command"]
