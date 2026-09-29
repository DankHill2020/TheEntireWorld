"""Canonical input-map normalization and actionable conflict diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class InputMapDiagnostic:
    severity: str
    code: str
    message: str
    context: str = ""
    action: str = ""
    binding: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InputMapAudit:
    contexts: tuple[dict[str, Any], ...]
    actions: dict[str, dict[str, Any]]
    diagnostics: tuple[InputMapDiagnostic, ...]

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "contexts": list(self.contexts),
            "actions": self.actions,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def audit_input_map(properties: Mapping[str, Any]) -> InputMapAudit:
    contexts = _normalize_contexts(properties.get("contexts"))
    actions = _normalize_actions(properties.get("actions"))
    diagnostics: list[InputMapDiagnostic] = []
    context_by_id = {str(item["id"]): item for item in contexts}
    if not contexts:
        diagnostics.append(InputMapDiagnostic("error", "missing_context", "Create at least one input context."))
    occupied: dict[tuple[str, str, str, tuple[str, ...]], tuple[str, int, bool]] = {}
    for action_name, action in actions.items():
        value_type = str(action.get("value_type") or "button")
        if value_type not in {"button", "axis1d", "axis2d", "axis3d"}:
            diagnostics.append(InputMapDiagnostic("error", "invalid_value_type", f"{action_name} has unsupported value type '{value_type}'.", action=action_name))
        bindings = list(action.get("bindings") or ())
        if not bindings:
            diagnostics.append(InputMapDiagnostic("warning", "unbound_action", f"{action_name} has no bindings.", action=action_name))
        seen_for_action: set[tuple[str, str, str, tuple[str, ...]]] = set()
        for binding in bindings:
            context = str(binding.get("context") or "Gameplay")
            device = str(binding.get("device") or "keyboard_mouse").casefold()
            key = str(binding.get("key") or "").strip()
            modifiers = tuple(sorted(str(value).casefold() for value in binding.get("modifiers") or ()))
            signature = (context, device, key.casefold(), modifiers)
            label = "+".join((*modifiers, key)) if modifiers else key
            if context not in context_by_id:
                diagnostics.append(InputMapDiagnostic("error", "unknown_context", f"{action_name} uses missing context '{context}'.", context, action_name, label))
            if not key:
                diagnostics.append(InputMapDiagnostic("error", "missing_key", f"{action_name} has a binding without a key.", context, action_name))
                continue
            if signature in seen_for_action:
                diagnostics.append(InputMapDiagnostic("warning", "duplicate_binding", f"{action_name} repeats {label} in {context}.", context, action_name, label))
            seen_for_action.add(signature)
            priority = int(context_by_id.get(context, {}).get("priority", 0))
            consumes = bool(binding.get("consume", True))
            previous = occupied.get(signature)
            if previous and previous[0] != action_name:
                diagnostics.append(InputMapDiagnostic(
                    "error", "binding_conflict",
                    f"{label} triggers both {previous[0]} and {action_name} in {context} at priority {priority}.",
                    context, action_name, label,
                ))
            else:
                occupied[signature] = (action_name, priority, consumes)
    # Same physical binding in different contexts is intentional when priorities differ; report shadowing.
    physical: dict[tuple[str, str, tuple[str, ...]], list[tuple[str, str, int]]] = {}
    for signature, (action, priority, _consume) in occupied.items():
        context, device, key, modifiers = signature
        physical.setdefault((device, key, modifiers), []).append((context, action, priority))
    for (_device, key, modifiers), uses in physical.items():
        priorities = {item[2] for item in uses}
        if len(uses) > 1 and len(priorities) > 1:
            ordered = sorted(uses, key=lambda item: item[2], reverse=True)
            label = "+".join((*modifiers, key)) if modifiers else key
            diagnostics.append(InputMapDiagnostic(
                "info", "priority_shadow", f"{label} resolves by context priority: " + " > ".join(f"{context}:{action}" for context, action, _priority in ordered),
                binding=label,
            ))
    return InputMapAudit(tuple(contexts), actions, tuple(diagnostics))


def _normalize_contexts(value: Any) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(value or ()):
        if isinstance(item, str):
            result.append({"id": item, "priority": 0, "enabled": True})
        elif isinstance(item, Mapping):
            identifier = str(item.get("id") or item.get("name") or f"Context{index + 1}")
            result.append({"id": identifier, "priority": int(item.get("priority", 0)), "enabled": bool(item.get("enabled", True))})
    return result


def _normalize_actions(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, raw in dict(value or {}).items():
        action = dict(raw) if isinstance(raw, Mapping) else {}
        bindings = []
        for binding in action.get("bindings") or ():
            if not isinstance(binding, Mapping):
                continue
            bindings.append({
                "context": str(binding.get("context") or "Gameplay"),
                "device": str(binding.get("device") or "keyboard_mouse"),
                "key": str(binding.get("key") or ""),
                "modifiers": [str(item) for item in binding.get("modifiers") or ()],
                "scale": float(binding.get("scale", 1.0)),
                "consume": bool(binding.get("consume", True)),
            })
        result[str(name)] = {"value_type": str(action.get("value_type") or "button"), "bindings": bindings}
    return result


__all__ = ["InputMapAudit", "InputMapDiagnostic", "audit_input_map"]
