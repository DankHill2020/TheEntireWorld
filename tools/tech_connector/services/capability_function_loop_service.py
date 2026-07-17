from __future__ import annotations

"""Capability-first deterministic function loop.

The model/planner may select a callable, but registered functions perform work.
The loop stops immediately when the objective is sufficient, fails safely, or
requires missing context/approval.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable
import time


@dataclass
class FunctionCallSpec:
    capability_id: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    mutating: bool = False
    requires_approval: bool = False
    validation: list[str] = field(default_factory=list)


@dataclass
class FunctionCallResult:
    capability_id: str
    ok: bool
    result: Any = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_hints: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityFunction:
    capability_id: str
    function: Callable[..., Any]
    mutating: bool = False
    validator: Callable[[Any], list[dict[str, Any]]] | None = None


class CapabilityFunctionRegistry:
    def __init__(self, functions: Iterable[CapabilityFunction] = ()) -> None:
        self._functions = {item.capability_id: item for item in functions}

    def register(self, item: CapabilityFunction) -> None:
        self._functions[item.capability_id] = item

    def get(self, capability_id: str) -> CapabilityFunction | None:
        return self._functions.get(capability_id)


class CapabilityFunctionLoop:
    def __init__(self, registry: CapabilityFunctionRegistry, *, max_steps: int = 12) -> None:
        self.registry = registry
        self.max_steps = max(1, int(max_steps))

    def run(
        self,
        state: Any,
        plan: Iterable[FunctionCallSpec],
        *,
        approval_granted: bool = False,
        sufficiency_check: Callable[[Any, FunctionCallResult, list[FunctionCallResult]], bool] | None = None,
    ) -> dict[str, Any]:
        results: list[FunctionCallResult] = []
        status = "completed"
        reason = "Function plan completed."
        for index, spec in enumerate(list(plan)[: self.max_steps], start=1):
            item = self.registry.get(spec.capability_id)
            if item is None:
                status = "missing_capability"
                reason = f"No registered callable for {spec.capability_id}."
                break
            if (spec.requires_approval or item.mutating or spec.mutating) and not approval_granted:
                status = "approval_required"
                reason = f"Approval required before {spec.capability_id}."
                break
            started = time.perf_counter()
            try:
                raw = item.function(*spec.args, **spec.kwargs)
                result = _normalize_result(spec.capability_id, raw)
            except Exception as exc:
                result = FunctionCallResult(spec.capability_id, False, errors=[str(exc)])
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            if item.validator and result.ok:
                validation = item.validator(result.result)
                failed = [entry for entry in validation if not entry.get("ok", False)]
                result.artifacts.append({"type": "validation", "results": validation})
                if failed:
                    result.ok = False
                    result.errors.extend(str(entry.get("message") or entry) for entry in failed)
            results.append(result)
            if hasattr(state, "diagnostics"):
                state.diagnostics.append({"event": "capability_function_result", "step": index, "result": result.to_dict()})
            if not result.ok:
                status = "function_failed"
                reason = f"{spec.capability_id} failed."
                break
            if sufficiency_check and sufficiency_check(state, result, results):
                status = "sufficient"
                reason = f"Objective satisfied after {spec.capability_id}."
                break
        if hasattr(state, "artifacts"):
            state.artifacts["capability_function_loop"] = {
                "status": status,
                "reason": reason,
                "results": [item.to_dict() for item in results],
            }
        return {"status": status, "reason": reason, "results": [item.to_dict() for item in results]}


def _normalize_result(capability_id: str, raw: Any) -> FunctionCallResult:
    if isinstance(raw, FunctionCallResult):
        return raw
    if isinstance(raw, dict):
        return FunctionCallResult(
            capability_id=capability_id,
            ok=bool(raw.get("ok", raw.get("success", True))),
            result=raw.get("result", raw.get("data", raw)),
            artifacts=list(raw.get("artifacts") or []),
            warnings=[str(item) for item in raw.get("warnings") or []],
            errors=[str(item) for item in raw.get("errors") or ([] if raw.get("error") is None else [raw.get("error")])],
            next_hints=[str(item) for item in raw.get("next_hints") or []],
        )
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], bool):
        return FunctionCallResult(capability_id, raw[0], result=raw[1], errors=[] if raw[0] else [str(raw[1])])
    return FunctionCallResult(capability_id, True, result=raw)
