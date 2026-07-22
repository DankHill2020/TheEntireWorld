from __future__ import annotations

"""Context provider layer for Tech Connector.

Each provider contributes factual, structured context. Providers should not mutate
the project and should not write directly into the chat thread. The prompt
staging layer decides what becomes visible in the composer.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol
from pathlib import Path
import json


@dataclass
class ContextItem:
    source: str
    title: str
    body: str
    kind: str = "context"
    tokens_estimate: int = 0
    priority: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    def estimate_tokens(self) -> int:
        if self.tokens_estimate:
            return self.tokens_estimate
        # Cheap approximation. Good enough for UI badges.
        return max(1, len(self.body) // 4)

    def to_prompt_text(self) -> str:
        meta = ""
        if self.metadata:
            compact = {
                k: v for k, v in self.metadata.items()
                if isinstance(v, (str, int, float, bool)) and v not in ("", None)
            }
            if compact:
                meta = "\nMetadata: " + json.dumps(compact, default=str)
        return f"### {self.title}\nSource: {self.source}\nKind: {self.kind}{meta}\n\n{self.body.strip()}"


class ContextProvider(Protocol):
    name: str

    def collect(self, request: str, *, project_root: str | None = None, max_chars: int = 6000) -> list[ContextItem]:
        ...


class ProblemFormulationContextProvider:
    """Form the user's problem before project or live-host context is retrieved."""

    name = "problem_formulation"

    def collect(
        self,
        request: str,
        *,
        project_root: str | None = None,
        max_chars: int = 6000,
    ) -> list[ContextItem]:
        try:
            from tech_connector.services.problem_formulation_service import (
                build_problem_formulation,
                problem_formulation_context,
            )
            formulation = build_problem_formulation(
                request,
                {"project_root": project_root or ""},
                context={},
            )
            return [
                ContextItem(
                    source=self.name,
                    title="Problem Formulation",
                    body=problem_formulation_context(
                        request,
                        {"project_root": project_root or ""},
                        max_chars=max_chars,
                    ),
                    kind="problem_formulation",
                    priority=120,
                    metadata={
                        "adequate": formulation.adequate,
                        "can_plan": formulation.can_plan,
                        "requires_clarification": formulation.requires_clarification,
                        "confidence": formulation.confidence,
                        "action_mode": formulation.action_mode,
                    },
                )
            ]
        except Exception as exc:
            return [
                ContextItem(
                    source=self.name,
                    title="Problem Formulation Failed",
                    body=str(exc),
                    kind="warning",
                    priority=115,
                )
            ]


class UnrealLiveContextProvider:
    """Collect live/cached Unreal facts through UnrealScanner and local intelligence."""

    name = "unreal_live"

    def collect(self, request: str, *, project_root: str | None = None, max_chars: int = 6000) -> list[ContextItem]:
        try:
            from tech_connector.bridges.unreal.unreal_scanner import UnrealScanner
        except Exception as exc:
            return [ContextItem(
                source=self.name,
                title="Unreal Context Unavailable",
                body=f"UnrealScanner import failed: {exc}",
                kind="warning",
                priority=90,
            )]

        scanner = UnrealScanner(project_root=project_root)
        items: list[ContextItem] = []

        try:
            status = scanner.context_status(request or "unreal project context", mode="quick")
            status_text = json.dumps(status, indent=2, default=str)
            items.append(ContextItem(
                source=self.name,
                title="Unreal Context Status",
                body=status_text[:max_chars],
                kind="runtime_status",
                priority=95,
                metadata={
                    "live": status.get("unreal_live_context"),
                    "cache_used": status.get("cache_used"),
                    "selected_assets": status.get("selected_assets"),
                    "selected_actors": status.get("selected_actors"),
                    "recommended_model": status.get("recommended_model"),
                },
            ))
        except Exception as exc:
            items.append(ContextItem(
                source=self.name,
                title="Unreal Context Status Failed",
                body=str(exc),
                kind="warning",
                priority=90,
            ))

        try:
            local = scanner.build_local_intelligence_context(request or "unreal project context")
            if local:
                items.append(ContextItem(
                    source=self.name,
                    title="Unreal Local Intelligence",
                    body=local[:max_chars],
                    kind="project_intelligence",
                    priority=100,
                ))
        except Exception as exc:
            items.append(ContextItem(
                source=self.name,
                title="Unreal Local Intelligence Failed",
                body=str(exc),
                kind="warning",
                priority=70,
            ))

        return items


class CodeIndexContextProvider:
    """Collect source-code intelligence from the canonical v2 knowledge index."""

    name = "code_index"

    def collect(self, request: str, *, project_root: str | None = None, max_chars: int = 6000) -> list[ContextItem]:
        items: list[ContextItem] = []

        # Use the canonical v2 project-search path so staged context matches
        # ProjectSearchProvider/ProjectHealthProvider behavior.
        try:
            from tech_connector.services.project_search_service import gather_project_search_context
            context = gather_project_search_context(request or "", active_path=None, limit=30)
            if context and "No indexed" not in context and "Project search error" not in context:
                items.append(ContextItem(
                    source=self.name,
                    title="Project Search Evidence",
                    body=context[:max_chars],
                    kind="code_index",
                    priority=85,
                    metadata={"index": "knowledge_index_v2"},
                ))
                return items
        except Exception:
            pass

        # Fallback: no indexed search available.
        root = Path(project_root or ".").resolve()
        items.append(ContextItem(
            source=self.name,
            title="Code Index Status",
            body=f"No searchable code index provider responded. Project root: {root}",
            kind="status",
            priority=30,
        ))
        return items


class CppWrapperContextProvider:
    """Stage wrapper feasibility context for Unreal C++ functions."""

    name = "cpp_wrapper"

    def collect(self, request: str, *, project_root: str | None = None, max_chars: int = 6000) -> list[ContextItem]:
        text = request or ""
        cppish = any(term in text.lower() for term in (
            "c++", "cpp", "wrapper", "blueprintcallable", "ufunction", "uclass",
            "python wrapper", "expose to python", "unreal python"
        ))
        if not cppish:
            return []

        try:
            from tech_connector.services.unreal.unreal_cpp_wrapper_service import plan_wrapper
        except Exception as exc:
            return [ContextItem(
                source=self.name,
                title="C++ Wrapper Planner Unavailable",
                body=f"Wrapper planner import failed: {exc}",
                kind="warning",
                priority=60,
            )]

        try:
            plan = plan_wrapper(text, project_root=project_root)
            if hasattr(plan, "to_dict"):
                plan_data = plan.to_dict()
            else:
                plan_data = plan
            return [ContextItem(
                source=self.name,
                title="Unreal C++ Wrapper Feasibility",
                body=json.dumps(plan_data, indent=2, default=str)[:max_chars],
                kind="wrapper_plan",
                priority=90,
            )]
        except Exception as exc:
            return [ContextItem(
                source=self.name,
                title="C++ Wrapper Feasibility Failed",
                body=str(exc),
                kind="warning",
                priority=60,
            )]


class ContextProviderRegistry:
    def __init__(self, providers: list[ContextProvider] | None = None):
        self.providers = providers or [
            ProblemFormulationContextProvider(),
            UnrealLiveContextProvider(),
            CodeIndexContextProvider(),
            CppWrapperContextProvider(),
        ]

    def collect(self, request: str, *, project_root: str | None = None, max_chars_per_provider: int = 6000) -> list[ContextItem]:
        items: list[ContextItem] = []
        for provider in self.providers:
            try:
                items.extend(provider.collect(request, project_root=project_root, max_chars=max_chars_per_provider))
            except Exception as exc:
                items.append(ContextItem(
                    source=getattr(provider, "name", provider.__class__.__name__),
                    title="Context Provider Failed",
                    body=str(exc),
                    kind="warning",
                    priority=10,
                ))
        return sorted(items, key=lambda item: item.priority, reverse=True)
