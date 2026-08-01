"""Smoke-test Tech Connector's separated reasoning runtime integration.

Run from ``C:/depot/tools``:

    python tech_connector/scripts/run_reasoning_runtime_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reasoning_runtime import ReasoningKernel
from reasoning_runtime.engine.request_context import RequestContext


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    sys.modules.pop("tech_connector", None)
    import reasoning_runtime  # noqa: F401

    _assert("tech_connector" not in sys.modules, "reasoning_runtime imported tech_connector")

    from tech_connector.adapters.domain_package import TechConnectorDomainPackage
    from tech_connector.engine.request_engine import RequestEngine

    kernel = ReasoningKernel()
    kernel.install(TechConnectorDomainPackage(project_root=str(REPO_ROOT)))
    run_result = kernel.run("inspect the project structure")
    adapter_counts = dict(run_result.metadata.get("adapter_counts") or {})

    expected_counts = {
        "context": 1,
        "reasoning": 1,
        "capability": 1,
        "validation": 1,
        "code_intelligence": 1,
        "code_understanding": 1,
        "rules": 1,
        "knowledge_sources": 1,
        "index_providers": 1,
    }
    for key, expected in expected_counts.items():
        _assert(
            adapter_counts.get(key) == expected,
            f"adapter count {key!r} was {adapter_counts.get(key)!r}, expected {expected}",
        )

    progress_events: list[tuple[str, str]] = []
    engine = RequestEngine(progress=lambda event: progress_events.append((event.stage, event.message)))
    result = engine.process(
        RequestContext(
            text="plan only: inspect the project structure",
            project_roots=(str(REPO_ROOT),),
            extras={"api_key": "must_not_leak", "safe_marker": "kept"},
        )
    )
    metadata = dict(result.metadata or {})
    runtime_metadata = dict(metadata.get("reasoning_runtime") or {})

    _assert(result.action in {"answer", "clarify", "passthrough", "error"}, "unexpected engine action")
    _assert(runtime_metadata.get("ok") is True, "RequestEngine did not attach runtime metadata")
    _assert("api_key" not in runtime_metadata, "runtime metadata leaked sensitive prompt context")
    _assert(progress_events, "RequestEngine emitted no progress events")
    _assert("tech_connector" in sys.modules, "Tech Connector was not imported for domain integration")

    print("reasoning_runtime smoke: OK")
    print(f"adapter_counts: {adapter_counts}")
    print(f"engine_result: {result.action} / {result.label}")
    print(f"progress_events: {len(progress_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
