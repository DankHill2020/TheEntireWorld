"""Domain-neutral request preparation helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from reasoning_runtime.engine.request_context import RequestContext, sanitize_prompt_context
from reasoning_runtime.kernel import KernelRunResult, ReasoningKernel
from reasoning_runtime.components.code_understanding import CodeUnderstandingRequest


def runtime_snapshot(result: KernelRunResult) -> dict[str, Any]:
    """Return stable metadata that UI/domain layers can attach to a request."""

    return {
        "ok": result.ok,
        "tools": [tool.name for tool in result.tools],
        "model_route": (
            {
                "provider": result.model_route.provider,
                "model": result.model_route.model,
                "tier": result.model_route.tier,
                "transport": result.model_route.transport,
            }
            if result.model_route
            else {}
        ),
        "rule_sets": [rule_set.name for rule_set in result.rule_sets],
        "adapter_counts": dict(result.metadata.get("adapter_counts") or {}),
    }


@dataclass
class RuntimeRequestPreparation:
    """Runs a reasoning kernel and returns a context carrying runtime metadata."""

    kernel: ReasoningKernel
    metadata_key: str = "reasoning_runtime"
    include_code_understanding: bool = True

    def prepare(self, context: RequestContext) -> tuple[RequestContext, KernelRunResult]:
        result = self.kernel.run(context.text)
        snapshot = runtime_snapshot(result)
        if self.include_code_understanding and self.kernel.code_understanding_providers:
            code_request = CodeUnderstandingRequest(
                query=context.text,
                project_roots=tuple(context.project_roots or ()),
                active_file=context.current_file_path,
                metadata={"active_tab": context.active_tab},
            )
            code_contexts = self.kernel.code_understanding_broker().understand(code_request)
            snapshot["code_understanding"] = self.kernel.code_understanding_broker().summarize(
                code_contexts
            )
        extras = sanitize_prompt_context(
            {
                **dict(context.extras or {}),
                self.metadata_key: snapshot,
            }
        )
        return replace(context, extras=extras), result
