"""Deterministic randomized coverage for action diagnosis contracts."""

from __future__ import annotations

import random
import string
from typing import Any

from tech_connector.services.action_execution_engine import (
    FAILURE_EXECUTION,
    FAILURE_OUTCOME,
    ActionExecutionEngine,
    ActionHandler,
    ActionHandlerRegistry,
    ExecutionContext,
)


RANDOM_SEED = 314_202_608


def _execute_once(raw: Any, *, expected_outcomes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Execute one raw result through the production supervisor.

    :param raw: Raw handler result.
    :param expected_outcomes: Optional outcome contracts.
    :return: Supervised result dictionary.
    """

    registry = ActionHandlerRegistry()
    registry.register(
        ActionHandler(
            "validate",
            "randomized-diagnosis",
            execute_fn=lambda _action, _context: raw,
        )
    )
    return ActionExecutionEngine(registry).execute_action(
        {
            "type": "validate",
            "id": "randomized",
            "max_retries": 0,
            "expected_outcomes": list(expected_outcomes or []),
        },
        ExecutionContext(),
    )


def _opaque_token(rng: random.Random, length: int = 12) -> str:
    """Build error text without relying on classification keywords.

    :param rng: Seeded random generator.
    :param length: Token length.
    :return: Random lowercase token.
    """

    return "".join(rng.choice(string.ascii_lowercase) for _ in range(length))


def test_randomized_implicit_failures_never_become_success() -> None:
    """Reject diverse failure evidence even when an ok field is absent."""

    rng = random.Random(RANDOM_SEED)
    failure_statuses = [
        "blocked",
        "cancelled",
        "error",
        "failed",
        "failure",
        "partial_failure",
        "rejected",
        "timed_out",
        "timeout",
    ]
    for index in range(160):
        kind = rng.choice(("status", "error", "exit_code", "exception"))
        if kind == "status":
            raw = {"status": rng.choice(failure_statuses)}
        elif kind == "error":
            raw = {"error": _opaque_token(rng)}
        elif kind == "exit_code":
            raw = {"exit_code": rng.randint(1, 255), "output": _opaque_token(rng)}
        else:
            raw = {"exception_type": rng.choice(("RuntimeError", "ValueError", "KeyError"))}

        result = _execute_once(raw)

        assert result["ok"] is False, (index, raw, result)
        assert result["failure_category"] == FAILURE_EXECUTION, (index, raw, result)


def test_randomized_falsey_values_are_distinct_from_missing_paths() -> None:
    """Preserve falsey values while safely rejecting missing list indexes."""

    rng = random.Random(RANDOM_SEED + 1)
    falsey_values: list[Any] = [False, 0, 0.0, "", [], {}, None]
    for index in range(120):
        value = rng.choice(falsey_values)
        raw = {"ok": True, "result": {"items": [{"value": value}]}}
        present = _execute_once(
            raw,
            expected_outcomes=[
                {"path": "result.items.0.value", "exists": True},
            ],
        )
        missing_index = rng.randint(1, 500)
        missing = _execute_once(
            raw,
            expected_outcomes=[
                {
                    "path": f"result.items.{missing_index}.value",
                    "exists": True,
                },
            ],
        )

        assert present["ok"] is True, (index, value, present)
        assert missing["ok"] is False, (index, missing_index, missing)
        assert missing["failure_category"] == FAILURE_OUTCOME


def test_randomized_host_substrings_do_not_override_code_errors() -> None:
    """Avoid environment diagnoses for identifiers that merely contain host."""

    rng = random.Random(RANDOM_SEED + 2)
    misleading_names = [
        "hostname",
        "localhost_value",
        "ghost_node",
        "cohost_record",
        "hostile_flag",
    ]
    for index in range(80):
        name = rng.choice(misleading_names) + "_" + _opaque_token(rng, 5)
        raw = {
            "ok": False,
            "error": f"AttributeError: object has no attribute {name!r}",
            "retryable": True,
        }

        result = _execute_once(raw)

        assert result["failure_category"] == FAILURE_EXECUTION, (index, raw, result)
        assert result["repair_plan"]["kind"] == "repair_code_or_api_usage"
