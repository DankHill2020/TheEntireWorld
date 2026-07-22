from __future__ import annotations

"""Deterministic prompt-route evaluation helpers.

The optional Ollama fuzzer discovers new phrasings; this module scores the
reviewed corpus that should stay stable in normal tests and local benchmarks.
"""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable


@dataclass
class PromptRouteEvalCase:
    id: str
    prompt: str
    expected_routes: set[str]
    category: str = "uncategorized"
    max_ms: float = 250.0
    expected_mutation_scope: str = ""


@dataclass
class PromptRouteEvalRow:
    id: str
    category: str
    prompt: str
    expected_routes: list[str]
    actual_route: str
    elapsed_ms: float
    ok: bool
    mutation_scope: str = ""
    expected_mutation_scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed_ms"] = round(self.elapsed_ms, 3)
        return data


@dataclass
class PromptRouteEvalReport:
    total: int
    passed: int
    failed: int
    accuracy: float
    average_ms: float
    max_ms: float
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    rows: list[PromptRouteEvalRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "accuracy": round(self.accuracy, 4),
            "average_ms": round(self.average_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "by_category": self.by_category,
            "rows": [row.to_dict() for row in self.rows],
        }


def load_prompt_route_eval_cases(path: str | Path) -> list[PromptRouteEvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[PromptRouteEvalCase] = []
    for item in data:
        expected = {
            str(route).strip()
            for route in item.get("expected_routes") or []
            if str(route).strip()
        }
        cases.append(
            PromptRouteEvalCase(
                id=str(item.get("id") or "").strip(),
                prompt=str(item.get("prompt") or ""),
                expected_routes=expected,
                category=str(item.get("category") or "uncategorized"),
                max_ms=float(item.get("max_ms") or 250.0),
                expected_mutation_scope=str(item.get("expected_mutation_scope") or ""),
            )
        )
    return cases


def evaluate_prompt_route_cases(
    cases: Iterable[PromptRouteEvalCase],
    *,
    classifier: Callable[..., Any] | None = None,
    project_roots: list[str] | None = None,
) -> PromptRouteEvalReport:
    if classifier is None:
        from tech_connector.services.prompt_route_service import classify_prompt_route

        classifier = classify_prompt_route

    rows: list[PromptRouteEvalRow] = []
    for case in cases:
        start = perf_counter()
        decision = classifier(case.prompt, project_roots=project_roots or [])
        elapsed_ms = (perf_counter() - start) * 1000.0
        actual_route = str(getattr(decision, "route", "") or "")
        mutation_scope = str(getattr(decision, "mutation_scope", "") or "")
        scope_ok = (
            not case.expected_mutation_scope
            or mutation_scope == case.expected_mutation_scope
        )
        rows.append(
            PromptRouteEvalRow(
                id=case.id,
                category=case.category,
                prompt=case.prompt,
                expected_routes=sorted(case.expected_routes),
                actual_route=actual_route,
                elapsed_ms=elapsed_ms,
                ok=actual_route in case.expected_routes and elapsed_ms <= case.max_ms and scope_ok,
                mutation_scope=mutation_scope,
                expected_mutation_scope=case.expected_mutation_scope,
            )
        )

    total = len(rows)
    passed = sum(1 for row in rows if row.ok)
    elapsed = [row.elapsed_ms for row in rows]
    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({row.category for row in rows}):
        subset = [row for row in rows if row.category == category]
        category_passed = sum(1 for row in subset if row.ok)
        category_elapsed = [row.elapsed_ms for row in subset]
        by_category[category] = {
            "total": len(subset),
            "passed": category_passed,
            "failed": len(subset) - category_passed,
            "accuracy": round(category_passed / len(subset), 4) if subset else 1.0,
            "average_ms": round(sum(category_elapsed) / len(category_elapsed), 3) if category_elapsed else 0.0,
            "max_ms": round(max(category_elapsed), 3) if category_elapsed else 0.0,
        }

    return PromptRouteEvalReport(
        total=total,
        passed=passed,
        failed=total - passed,
        accuracy=(passed / total) if total else 1.0,
        average_ms=(sum(elapsed) / len(elapsed)) if elapsed else 0.0,
        max_ms=max(elapsed) if elapsed else 0.0,
        by_category=by_category,
        rows=rows,
    )
