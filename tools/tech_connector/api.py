"""Headless public API for licensed Tech Connector function access.

This module is intentionally UI-free. It is the supported Python entry point
for scripts, services, tests, and future local/hosted API servers that need to
use Tech Connector capabilities without starting the Qt desktop application.
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from tech_connector.licensing.context import LicensingContext
from tech_connector.models.constants import APP_DIR, APP_ROOT, APP_VERSION
from tech_connector.router.command_router import CommandRouter
from tech_connector.services.action_execution_engine import (
    ActionExecutionEngine,
    ExecutionContext,
    default_action_handler_registry,
)
from tech_connector.services.action_planner_service import plan_prompt_to_action_graph, workflow_plan_from_action_graph
from tech_connector.services.api_feature_registry_service import (
    APIFeatureDescriptor,
    APIFeatureRegistry,
)
from tech_connector.services.conversation_workspace_service import compatibility_snapshot
from tech_connector.services.license_entitlement_service import (
    LICENSE_TOKEN_PREFIX,
    LicenseEntitlement,
    entitlement_from_signed_evaluation,
    entitlement_status_from_entitlement,
    entitlement_status_row,
    verify_entitlement,
)
from tech_connector.services.llm_request_queue_service import (
    cancel_llm_request as _cancel_llm_request,
    llm_request_queue_snapshot as _llm_request_queue_snapshot,
)
from tech_connector.services.project_validation_intent_service import classify_validation_intent
from tech_connector.services.prompt.prompt_resource_orchestration_service import (
    build_resource_orchestration_plan,
)
from tech_connector.services.reasoning.request_frame_service import analyze_request_frame
from tech_connector.services.settings_service import load_settings
from tech_connector.services.tool_discovery_service import list_internal_functions
from tech_connector.services.usage_provenance_service import (
    apply_python_provenance,
    build_usage_tag,
    write_project_provenance_marker,
)
from tech_connector.services.validation_planner_service import plan_validation_for_paths
from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph


DCC_API_ALIASES: dict[str, dict[str, str]] = {
    "maya": {
        "create_rig_mapping": "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
        "create_rig_from_mapping": "maya_tools.Rigging.create_rig.create_rig_from_mapping",
        "create_rig": "maya_tools.Rigging.create_rig.create_rig_from_mapping",
    },
    "unreal": {
        "find_asset_path_by_name": "unreal_tools.assets.find_asset_path_by_name",
        "find_assets": "unreal_tools.assets.find_asset_path_by_name",
    },
}

_DEFAULT_UI_WINDOW: Any | None = None


def register_default_ui_window(window: Any | None) -> None:
    global _DEFAULT_UI_WINDOW
    _DEFAULT_UI_WINDOW = window


def get_default_ui_window() -> Any | None:
    return _DEFAULT_UI_WINDOW

PROMPT_CHAIN_SUCCESS_STATUSES = {"completed", "dry_run"}
API_VERSION = "2.0"
API_SCHEMA = "tech_connector.api.v2"


def _normalize_host(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _normalize_api_name(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


class _WorkflowPlanView:
    def __init__(self, plan: dict[str, Any]) -> None:
        self._plan = plan

    def manifest_data_links(self) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        for item in self._plan.get("data_links") or []:
            from_step = int(item.get("from_step") or 0)
            to_step = int(item.get("to_step") or 0)
            if not from_step or not to_step:
                continue
            links.append(
                {
                    "from": f"step{from_step}.{item.get('from_output') or 'result'}",
                    "to": f"step{to_step}.{item.get('to_input') or 'value'}",
                }
            )
        return links

    def manifest_flow_links(self) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        for item in self._plan.get("flow_links") or []:
            from_step = int(item.get("from_step") or 0)
            to_step = int(item.get("to_step") or 0)
            if from_step and to_step:
                links.append({"from": f"step{from_step}", "to": f"step{to_step}"})
        return links


@dataclass(frozen=True)
class APIResult:
    ok: bool
    result: Any = None
    error: str = ""
    entitlement: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    error_detail: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.ok and self.error and not self.error_detail:
            object.__setattr__(self, "error_detail", _classify_api_error(self.error))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "error_detail": self.error_detail or {},
            "entitlement": self.entitlement or {},
            "provenance": self.provenance or {},
        }

    def unwrap(self) -> Any:
        """Return the result or raise a structured exception for simple scripts."""
        if self.ok:
            return self.result
        detail = self.error_detail or _classify_api_error(self.error)
        raise TechConnectorAPIError(
            str(detail.get("message") or self.error or "Tech Connector API request failed."),
            code=str(detail.get("code") or "api_error"),
            retryable=bool(detail.get("retryable")),
            suggestion=str(detail.get("suggestion") or ""),
        )

    def __bool__(self) -> bool:
        return self.ok


class TechConnectorAPIError(RuntimeError):
    """Exception raised by :meth:`APIResult.unwrap` with machine-readable context."""

    def __init__(
        self, message: str, *, code: str = "api_error", retryable: bool = False,
        suggestion: str = "",
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.retryable = bool(retryable)
        self.suggestion = str(suggestion)


def _classify_api_error(message: str) -> dict[str, Any]:
    text = str(message or "Tech Connector API request failed.").strip()
    lowered = text.casefold()
    code = "internal_error"
    retryable = False
    suggestion = "Review the error and retry with valid inputs."
    if any(token in lowered for token in ("license", "permission", "approved=true", "not entitled")):
        code = "permission_denied"
        suggestion = "Verify entitlement or explicitly approve the requested mutation."
    elif any(token in lowered for token in ("not found", "unknown api", "unknown reasoning", "unknown asset", "unknown kingdom", "unknown feature", "unknown operation")):
        code = "not_found"
        suggestion = "Use API discovery to confirm the feature, operation, tool, or asset identifier."
    elif any(token in lowered for token in ("must not be empty", "required", "invalid", "unsupported", "choose one of")):
        code = "invalid_argument"
        suggestion = "Inspect the operation help and correct the supplied arguments."
    elif any(token in lowered for token in ("offline", "unavailable", "timed out", "timeout", "connection")):
        code = "temporarily_unavailable"
        retryable = True
        suggestion = "Check provider or bridge status, then retry the request."
    return {
        "schema": f"{API_SCHEMA}.error",
        "code": code,
        "message": text,
        "retryable": retryable,
        "suggestion": suggestion,
    }


def _serialize_public_value(value: Any) -> Any:
    """Convert runtime records into JSON-safe public API values."""
    if is_dataclass(value):
        return _serialize_public_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _serialize_public_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_serialize_public_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AIAPINamespace:
    """Simple, provider-neutral model discovery, routing, and generation."""

    def __init__(self, api: "TechConnectorHeadlessAPI") -> None:
        self._api = api

    def _resolve(self, model: str, depth: str):
        from tech_connector.services.code_prompt_profile_service import (
            PROMPT_DEPTHS, openai_execution_options, preferred_openai_model,
        )
        from tech_connector.services.llm_router_service import resolve_llm_provider_route
        from tech_connector.services.model_provider_service import provider_for_model

        depth = str(depth or "balanced").strip().lower()
        if depth not in PROMPT_DEPTHS:
            raise ValueError(
                f"Unknown AI depth '{depth}'. Choose one of: {', '.join(PROMPT_DEPTHS)}."
            )
        selected = str(
            model or self._api.settings.get("model")
            or self._api.settings.get("cloud_provider_model")
            or self._api.settings.get("general_model")
            or "ollama:qwen3.5:4b"
        ).strip()
        selected_name = selected.partition(":")[2].lower()
        if (
            provider_for_model(selected) == "openai"
            and bool(self._api.settings.get("auto_select_openai_model_by_depth", True))
            and (
                not selected_name
                or selected_name.startswith(("gpt-6", "gpt-5.6", "gpt-5.3-codex"))
            )
        ):
            selected = "openai:" + preferred_openai_model(depth)
        route_settings = dict(self._api.settings)
        route_settings["code_prompt_depth"] = depth
        route = resolve_llm_provider_route(selected, route_settings)
        options = openai_execution_options({"depth": depth})
        options["store"] = bool(self._api.settings.get("openai_store_responses", True))
        return selected, depth, route, options

    @staticmethod
    def _public_route(route: Any) -> dict[str, Any]:
        return {
            "provider": str(route.provider),
            "model": str(route.model),
            "cloud_active": bool(route.cloud_active),
            "transport": str(
                route.transport or ("local" if not route.cloud_active else "api_key")
            ),
        }

    def models(self) -> APIResult:
        """List safe provider metadata and available model identifiers."""
        try:
            from tech_connector.services.model_provider_service import (
                PROVIDER_ORDER, PROVIDERS, models_for_provider, provider_api_key,
                provider_has_credentials,
            )
            entitlement = self._api._require_unlocked()
            cached = dict(self._api.settings.get("provider_model_catalog") or {})
            providers = [
                {
                    "id": provider_id,
                    "name": PROVIDERS[provider_id].display_name,
                    "connected": bool(
                        provider_has_credentials(provider_id, probe_account=False)
                        or provider_api_key(provider_id, self._api.settings)
                    ),
                    "local": provider_id == "ollama",
                    "models": list(models_for_provider(provider_id, cached)),
                    "setup_url": PROVIDERS[provider_id].setup_url,
                }
                for provider_id in PROVIDER_ORDER
            ]
            return APIResult(True, {
                "schema": f"{API_SCHEMA}.ai_models",
                "providers": providers,
                "depths": ["fast", "balanced", "deep", "maximum"],
                "source_mode": self._api.settings.get(
                    "model_source_mode", "auto_with_local_fallback"
                ),
            }, entitlement=entitlement.to_dict())
        except Exception as exc:
            return APIResult(False, error=str(exc))

    def local_recommendation(self) -> APIResult:
        """Describe the hardware-aware local model lanes without changing state."""
        try:
            from tech_connector.services.local_model_optimizer_service import (
                recommend_local_models,
            )
            from tech_connector.services.ollama_service import installed_ollama_models

            entitlement = self._api._require_unlocked()
            recommendation = recommend_local_models(installed_ollama_models())
            return APIResult(
                True,
                {
                    "schema": f"{API_SCHEMA}.ai_local_recommendation",
                    **recommendation,
                },
                entitlement=entitlement.to_dict(),
            )
        except Exception as exc:
            return APIResult(False, error=str(exc))

    def benchmark_local(
        self,
        *,
        model: str = "",
        prompt: str = "",
        num_predict: int = 128,
        num_ctx: int = 4096,
        timeout: int = 300,
    ) -> APIResult:
        """Measure a local Ollama model with a small deterministic speed probe."""
        try:
            from tech_connector.services.local_model_optimizer_service import (
                benchmark_local_model,
                recommend_local_models,
            )
            from tech_connector.services.ollama_service import installed_ollama_models

            entitlement = self._api._require_unlocked()
            installed = installed_ollama_models()
            recommendation = recommend_local_models(installed)
            selected = str(model or recommendation["active"]["general"])
            metrics = benchmark_local_model(
                selected,
                prompt=str(prompt or "Write a concise Python function that groups paths by extension."),
                num_predict=num_predict,
                num_ctx=num_ctx,
                timeout=timeout,
            )
            return APIResult(
                True,
                {"schema": f"{API_SCHEMA}.ai_local_benchmark", **metrics},
                entitlement=entitlement.to_dict(),
                provenance=self._api._tag(
                    entitlement, operation="ai.benchmark_local"
                ),
            )
        except Exception as exc:
            return APIResult(False, error=str(exc))

    def route(self, *, model: str = "", depth: str = "balanced") -> APIResult:
        """Preview the exact credential-free route used for generation."""
        try:
            entitlement = self._api._require_unlocked()
            selected, depth, route, options = self._resolve(model, depth)
            return APIResult(True, {
                "schema": f"{API_SCHEMA}.ai_route",
                "requested_model": selected,
                "depth": depth,
                "route": self._public_route(route),
                "options": options if route.provider == "openai" else {},
            }, entitlement=entitlement.to_dict())
        except Exception as exc:
            return APIResult(False, error=str(exc))

    def generate(
        self, prompt: str, *, system: str = "", model: str = "",
        depth: str = "balanced", response_format: dict[str, Any] | str | None = None,
        options: dict[str, Any] | None = None, timeout: int = 120,
        allow_local_fallback: bool = False,
    ) -> APIResult:
        """Generate text with one stable, inspectable provider route."""
        try:
            from tech_connector.services.llm_router_service import generate_llm_response
            if not str(prompt or "").strip():
                raise ValueError("prompt must not be empty")
            entitlement = self._api._require_unlocked()
            selected, depth, route, defaults = self._resolve(model, depth)
            effective_options = dict(defaults if route.provider == "openai" else {})
            effective_options.update(dict(options or {}))
            text = generate_llm_response(
                route.model, str(prompt), system=str(system or ""),
                response_format=response_format, options=effective_options,
                timeout=max(1, int(timeout)), provider_route=route,
                allow_cloud_fallback=bool(allow_local_fallback),
            )
            return APIResult(True, {
                "schema": f"{API_SCHEMA}.ai_response",
                "text": text,
                "requested_model": selected,
                "depth": depth,
                "route": self._public_route(route),
            }, entitlement=entitlement.to_dict(),
                provenance=self._api._tag(entitlement, operation="ai.generate"))
        except Exception as exc:
            return APIResult(False, error=str(exc))

class ReasoningRuntimeNamespace:
    """Public access to the shared Tech Connector reasoning runtime."""

    def __init__(self, api: "TechConnectorHeadlessAPI") -> None:
        self._api = api
        self._kernel = None

    def _kernel_instance(self):
        if self._kernel is None:
            from reasoning_runtime import ReasoningKernel
            from tech_connector.adapters.domain_package import TechConnectorDomainPackage

            kernel = self._api.runtime_kernel
            if kernel is None:
                kernel = ReasoningKernel()
                kernel.install(
                    TechConnectorDomainPackage(
                        command_router=self._api.command_router,
                        project_root=self._api.project_root,
                        settings=self._api.settings,
                    )
                )
            for runtime_package in self._api.runtime_packages:
                kernel.install(runtime_package)
            self._kernel = kernel
        return self._kernel

    def _request_context(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ):
        from reasoning_runtime.engine.request_context import (
            RequestContext,
            sanitize_prompt_context,
        )

        payload = dict(context or {})
        extras = dict(payload.pop("extras", {}) or {})
        thread = payload.pop("thread", payload.pop("messages", None))
        if thread is not None:
            extras["conversation_history"] = thread
        interaction_surface = str(payload.pop("interaction_surface", "") or "")
        surface_alias = str(payload.pop("surface", "") or "")
        if not payload.get("active_tab"):
            payload["active_tab"] = interaction_surface or surface_alias or "API"

        known_fields = {
            "active_tab",
            "current_file_path",
            "open_file_paths",
            "selection_text",
            "project_roots",
            "attached_images",
            "model",
            "index_state",
        }
        for key in list(payload):
            if key not in known_fields:
                extras[key] = payload.pop(key)

        roots = payload.get("project_roots")
        if roots is None:
            roots = _project_roots(self._api.project_root, self._api.settings)
        model = str(
            payload.get("model")
            or self._api.settings.get("model")
            or self._api.settings.get("general_model")
            or ""
        )
        return RequestContext(
            text=str(prompt or ""),
            active_tab=str(payload.get("active_tab") or "API"),
            current_file_path=str(payload.get("current_file_path") or ""),
            open_file_paths=tuple(str(item) for item in payload.get("open_file_paths") or ()),
            selection_text=str(payload.get("selection_text") or ""),
            project_roots=tuple(str(item) for item in roots or ()),
            attached_images=tuple(str(item) for item in payload.get("attached_images") or ()),
            model=model,
            index_state=str(payload.get("index_state") or "unknown"),
            extras=sanitize_prompt_context(extras),
        )

    @staticmethod
    def _adapter_counts(kernel) -> dict[str, int]:
        return {
            "context": len(kernel.context_adapters),
            "reasoning": len(kernel.reasoning_adapters),
            "capability": len(kernel.capability_bridges),
            "validation": len(kernel.validation_contracts),
            "evidence": len(kernel.evidence_policies),
            "escalation": len(kernel.escalation_policies),
            "code_intelligence": len(kernel.code_intelligence_adapters),
            "code_understanding": len(kernel.code_understanding_providers),
            "rules": len(kernel.rule_providers),
            "knowledge_sources": len(kernel.knowledge_sources),
            "index_providers": len(kernel.index_providers),
            "symbol_lookup_providers": len(kernel.symbol_lookup_providers),
            "action_planners": len(kernel.action_planners),
            "reasoning_layers": len(kernel.reasoning_pipeline.layers),
        }

    def capabilities(self) -> dict[str, Any]:
        entitlement = self._api._require_unlocked()
        kernel = self._kernel_instance()
        feature_manifest = self._api.features.manifest()
        return {
            "schema": f"{API_SCHEMA}.capabilities",
            "api_version": API_VERSION,
            "features": [
                feature["feature_id"]
                for feature in feature_manifest["features"]
                if feature["available"]
            ],
            "feature_manifest": feature_manifest,
            "adapter_counts": self._adapter_counts(kernel),
            "dcc_hosts": sorted(self._api.dcc.__dict__.keys() - {"_api"}),
            "entitlement": entitlement.to_dict(),
        }

    def snapshot(
        self,
        prompt: str = "",
        *,
        context: dict[str, Any] | None = None,
    ) -> APIResult:
        try:
            entitlement = self._api._require_unlocked()
            kernel = self._kernel_instance()
            result = kernel.run(str(prompt or ""))
            return APIResult(
                ok=bool(result.ok),
                result={
                    "schema": f"{API_SCHEMA}.reasoning_snapshot",
                    "request_context": _serialize_public_value(
                        self._request_context(prompt, context)
                    ),
                    "runtime": _serialize_public_value(result),
                },
                error="" if result.ok else "Runtime preconditions did not pass.",
                entitlement=entitlement.to_dict(),
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def prepare(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> APIResult:
        try:
            from reasoning_runtime import RuntimeRequestPreparation

            entitlement = self._api._require_unlocked()
            prepared, result = RuntimeRequestPreparation(
                self._kernel_instance()
            ).prepare(self._request_context(prompt, context))
            return APIResult(
                ok=bool(result.ok),
                result={
                    "schema": f"{API_SCHEMA}.prepared_request",
                    "context": _serialize_public_value(prepared),
                    "runtime": _serialize_public_value(result),
                },
                error="" if result.ok else "Runtime preconditions did not pass.",
                entitlement=entitlement.to_dict(),
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def run(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        activity_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> APIResult:
        try:
            from tech_connector.engine.request_engine import RequestEngine

            entitlement = self._api._require_unlocked()
            progress_events: list[dict[str, Any]] = []
            activity_events: list[dict[str, Any]] = []

            def capture_progress(event) -> None:
                payload = _serialize_public_value(event)
                progress_events.append(payload)
                if progress_callback is not None:
                    progress_callback(payload)

            def capture_activity(event) -> None:
                payload = _serialize_public_value(event)
                activity_events.append(payload)
                if activity_callback is not None:
                    activity_callback(payload)

            engine = RequestEngine(
                progress=capture_progress,
                activity=capture_activity,
                runtime_kernel=self._kernel_instance(),
            )
            response = engine.process(self._request_context(prompt, context))
            response_payload = _serialize_public_value(response)
            ok = str(response.action or "").lower() not in {"error", "failed"}
            production_readiness = dict(
                (response.metadata or {}).get("production_readiness") or {}
            )
            runtime_metadata = dict(
                (response.metadata or {}).get("reasoning_runtime") or {}
            )
            if production_readiness:
                runtime_metadata["production_readiness"] = production_readiness
            tag = self._api._tag(entitlement, operation="reasoning.run")
            return APIResult(
                ok=ok,
                result={
                    "schema": f"{API_SCHEMA}.reasoning_response",
                    "response": response_payload,
                    "progress": progress_events,
                    "activity": activity_events,
                    "runtime": runtime_metadata,
                    "production_readiness": production_readiness,
                },
                error="" if ok else str(response.text or "Reasoning request failed."),
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def run_chain(
        self,
        prompts: str | list[str] | tuple[str, ...],
        *,
        context: dict[str, Any] | None = None,
        stop_on_error: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        activity_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> APIResult:
        """Run sequential requests with bounded history and reusable workspace state."""
        from tech_connector.services.operation_memory_service import update_operation_memory

        steps = _normalize_prompt_chain(prompts)
        if not steps:
            return APIResult(ok=False, error="Prompt chain is empty.")
        base_context = dict(context or {})
        memory = dict(base_context.pop("operation_memory", {}) or {})
        workspace = dict(base_context.pop("conversation_workspace", {}) or {})
        if workspace:
            memory["conversation_workspace"] = workspace
        prior_metadata = dict(base_context.pop("prior_result_metadata", {}) or {})
        history = list(base_context.pop("thread", base_context.pop("messages", [])) or [])[-12:]
        results: list[dict[str, Any]] = []
        stopped = False
        stop_reason = ""
        entitlement: dict[str, Any] | None = None
        provenance: dict[str, Any] | None = None
        for index, prompt in enumerate(steps, start=1):
            step_context = {
                **base_context,
                "operation_memory": memory,
                "conversation_workspace": workspace,
                "prior_result_metadata": prior_metadata,
                "thread": history,
            }

            def step_progress(event: dict[str, Any]) -> None:
                if progress_callback:
                    progress_callback({"chain_index": index, "chain_count": len(steps), **event})

            def step_activity(event: dict[str, Any]) -> None:
                if activity_callback:
                    activity_callback({"chain_index": index, "chain_count": len(steps), **event})

            response = self.run(
                prompt,
                context=step_context,
                progress_callback=step_progress,
                activity_callback=step_activity,
            )
            entitlement = response.entitlement or entitlement
            provenance = response.provenance or provenance
            payload = dict(response.result or {}) if isinstance(response.result, dict) else {}
            answer = dict(payload.get("response") or {})
            action = str(answer.get("action") or "").lower()
            results.append({"index": index, "prompt": prompt, "ok": response.ok, "response": answer, "error": response.error})
            if response.ok:
                metadata = dict(answer.get("metadata") or {})
                prior_metadata = metadata
                route = dict(metadata.get("route_decision") or {})
                memory = update_operation_memory(memory, route_decision=route, result=metadata)
                workspace = dict(memory.get("conversation_workspace") or workspace)
                history.extend((
                    {"role": "user", "content": prompt[:3000]},
                    {"role": "assistant", "content": str(answer.get("text") or "")[:3000]},
                ))
                history = history[-12:]
            if action == "clarify" or (not response.ok and stop_on_error):
                stopped = True
                stop_reason = (
                    f"Step {index} needs clarification."
                    if action == "clarify" else f"Step {index} failed: {response.error}"
                )
                break
        complete = len(results) == len(steps) and all(row["ok"] for row in results)
        return APIResult(
            ok=complete and not stopped,
            result={
                "schema": f"{API_SCHEMA}.reasoning_chain",
                "step_count": len(steps),
                "completed_steps": len(results),
                "stopped": stopped,
                "stop_reason": stop_reason,
                "steps": results,
                "state": {"operation_memory": memory, "conversation_workspace": workspace},
            },
            error="" if complete and not stopped else stop_reason or "One or more prompts failed.",
            entitlement=entitlement,
            provenance=provenance,
        )

    def tools(self) -> APIResult:
        try:
            entitlement = self._api._require_unlocked()
            tools = self._kernel_instance().list_tools()
            return APIResult(
                ok=True,
                result={
                    "schema": f"{API_SCHEMA}.runtime_tools",
                    "tools": _serialize_public_value(tools),
                },
                entitlement=entitlement.to_dict(),
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        dry_run: bool = False,
    ) -> APIResult:
        try:
            entitlement = self._api._require_unlocked()
            arguments = dict(arguments or {})
            for bridge in self._kernel_instance().capability_bridges:
                specs = {tool.name: tool for tool in bridge.get_tools()}
                spec = specs.get(str(tool_name or ""))
                if spec is None:
                    continue
                if dry_run:
                    return APIResult(
                        ok=True,
                        result={
                            "schema": f"{API_SCHEMA}.runtime_tool_dry_run",
                            "tool": _serialize_public_value(spec),
                            "arguments": _serialize_public_value(arguments),
                            "executed": False,
                        },
                        entitlement=entitlement.to_dict(),
                    )
                if spec.mutability != "read_only" and not approved:
                    return APIResult(
                        ok=False,
                        error=(
                            f"Runtime tool '{tool_name}' is {spec.mutability} and requires "
                            "approved=True before execution."
                        ),
                        entitlement=entitlement.to_dict(),
                    )
                result = bridge.execute_tool(tool_name, arguments)
                tag = self._api._tag(
                    entitlement,
                    operation=f"reasoning.execute_tool:{tool_name}",
                )
                return APIResult(
                    ok=bool(result.ok),
                    result={
                        "schema": f"{API_SCHEMA}.runtime_tool_result",
                        "tool": _serialize_public_value(spec),
                        "execution": _serialize_public_value(result),
                    },
                    error=str(result.error or ""),
                    entitlement=entitlement.to_dict(),
                    provenance=tag,
                )
            return APIResult(
                ok=False,
                error=f"Unknown reasoning runtime tool: {tool_name}",
                entitlement=entitlement.to_dict(),
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))


class APIFeatureNamespace:
    """Discover and invoke independently registered Tech Connector API features."""

    def __init__(self, api: "TechConnectorHeadlessAPI") -> None:
        self._api = api
        self._registry = APIFeatureRegistry()
        self._populated = False

    def _ensure_populated(self) -> None:
        if self._populated:
            return
        registry = APIFeatureRegistry()
        self._api._populate_feature_registry(registry)
        self._registry = registry
        self._populated = True

    def register(
        self,
        descriptor: APIFeatureDescriptor,
        handlers: dict[str, Callable[..., Any]] | None = None,
        *,
        replace: bool = False,
    ) -> None:
        self._ensure_populated()
        self._registry.register(descriptor, handlers, replace=replace)

    def list(
        self,
        *,
        category: str = "",
        available_only: bool = True,
        access: str = "",
        lifecycle_stage: str = "",
        owner_feature_id: str = "",
    ) -> list[dict[str, Any]]:
        self._api._require_unlocked()
        self._ensure_populated()
        return [
            descriptor.to_dict()
            for descriptor in self._registry.list(
                category=category,
                available_only=available_only,
                access=access,
                lifecycle_stage=lifecycle_stage,
                owner_feature_id=owner_feature_id,
            )
        ]

    def get(self, feature_id: str) -> dict[str, Any]:
        self._api._require_unlocked()
        self._ensure_populated()
        descriptor = self._registry.get(feature_id)
        return descriptor.to_dict() if descriptor is not None else {}

    def search(
        self, query: str, *, category: str = "", available_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Search feature IDs, descriptions, categories, and operation names."""
        self._api._require_unlocked()
        self._ensure_populated()
        return [
            descriptor.to_dict()
            for descriptor in self._registry.search(
                query, category=category, available_only=available_only,
            )
        ]

    def describe(self, feature_id: str, operation: str = "") -> dict[str, Any]:
        """Return callable signatures, defaults, docs, and explicit schemas."""
        self._api._require_unlocked()
        self._ensure_populated()
        descriptor = self._registry.get(feature_id)
        if descriptor is None:
            raise KeyError(f"Unknown API feature: {feature_id}")
        requested = str(operation or "").strip()
        if requested and requested not in descriptor.operations:
            raise KeyError(
                f"Feature '{feature_id}' does not declare operation '{requested}'."
            )
        operations = []
        for operation_name in descriptor.operations:
            if requested and operation_name != requested:
                continue
            handler = self._registry.handler(descriptor.feature_id, operation_name)
            parameters = []
            signature_text = ""
            documentation = ""
            if handler is not None:
                signature = inspect.signature(handler)
                signature_text = str(signature)
                documentation = inspect.getdoc(handler) or ""
                for parameter in signature.parameters.values():
                    annotation = parameter.annotation
                    annotation_name = (
                        ""
                        if annotation is inspect.Parameter.empty
                        else getattr(annotation, "__name__", str(annotation))
                    )
                    has_default = parameter.default is not inspect.Parameter.empty
                    parameters.append({
                        "name": parameter.name,
                        "kind": parameter.kind.name.lower(),
                        "required": not has_default
                        and parameter.kind not in {
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD,
                        },
                        "annotation": annotation_name,
                        "has_default": has_default,
                        "default": (
                            _serialize_public_value(parameter.default)
                            if has_default else None
                        ),
                    })
            operations.append({
                "name": operation_name,
                "callable": handler is not None,
                "signature": signature_text,
                "parameters": parameters,
                "documentation": documentation,
                "schema": dict(descriptor.operation_schemas.get(operation_name) or {}),
            })
        return {
            "schema": f"{API_SCHEMA}.feature_help",
            "feature": descriptor.to_dict(),
            "operations": operations,
        }

    def manifest(self) -> dict[str, Any]:
        self._api._require_unlocked()
        self._ensure_populated()
        return self._registry.manifest()

    def invoke(
        self,
        feature_id: str,
        operation: str,
        **kwargs: Any,
    ) -> APIResult:
        try:
            entitlement = self._api._require_unlocked()
            self._ensure_populated()
            value = self._registry.invoke(feature_id, operation, **kwargs)
            if isinstance(value, APIResult):
                return value
            return APIResult(
                ok=True,
                result={
                    "schema": f"{API_SCHEMA}.feature_result",
                    "feature_id": feature_id,
                    "operation": operation,
                    "value": _serialize_public_value(value),
                },
                entitlement=entitlement.to_dict(),
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))


def _project_roots(project_root: str | Path | None, settings: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()

    def add(value: str | Path | None) -> None:
        text = str(value or "").strip()
        if not text:
            return
        resolved = str(Path(text).expanduser().resolve())
        key = resolved.casefold()
        if key not in seen:
            seen.add(key)
            roots.append(resolved)

    add(project_root)
    add(settings.get("active_project"))
    for extra in settings.get("extra_dirs") or ():
        add(extra)
    add(APP_ROOT.parent)
    return roots


def _import_callable(entry_point: str, *, extra_roots: list[str] | None = None) -> Callable[..., Any]:
    entry = str(entry_point or "").strip()
    if ":" in entry:
        module_name, symbol_path = entry.split(":", 1)
    else:
        module_name, _, symbol_path = entry.rpartition(".")
    if not module_name or not symbol_path:
        raise ValueError("entry_point must look like 'package.module:function' or 'package.module.function'.")
    for root in reversed(extra_roots or []):
        if root and root not in sys.path:
            sys.path.insert(0, root)
    module = importlib.import_module(module_name)
    target: Any = module
    for part in symbol_path.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"Entry point is not callable: {entry_point}")
    return target


def _normalize_prompt_chain(prompts: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(prompts, str):
        text = prompts.replace("\r\n", "\n").strip()
        if not text:
            return []
        if "\n" in text:
            parts = text.splitlines()
        elif "->" in text:
            parts = text.split("->")
        elif "=>" in text:
            parts = text.split("=>")
        else:
            parts = re.split(r"\bthen\b", text, flags=re.IGNORECASE)
        cleaned = []
        for part in parts:
            step = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", str(part)).strip()
            if step:
                cleaned.append(step)
        return cleaned
    return [str(item).strip() for item in prompts if str(item).strip()]


def _execution_report_succeeded(report: dict[str, Any]) -> bool:
    status = str((report or {}).get("status") or "").strip().lower()
    return status in PROMPT_CHAIN_SUCCESS_STATUSES


class TechConnectorHeadlessAPI:
    """Official, UI-independent API for Tech Connector automation."""

    def __init__(
        self,
        *,
        settings: dict[str, Any] | None = None,
        project_root: str | Path | None = None,
        license_secret: str | None = None,
        require_entitlement: bool = True,
        command_router: Any = None,
        runtime_kernel: Any = None,
        runtime_packages: Iterable[Any] | None = None,
        ui_window: Any | None = None,
        licensing_context: LicensingContext | None = None,
        commercial_use: bool = True,
        app_major_version: str | None = None,
    ) -> None:
        self.settings = dict(settings if settings is not None else load_settings())
        self.project_root = str(Path(project_root).expanduser().resolve()) if project_root else str(self.settings.get("active_project") or "")
        self.license_secret = license_secret
        from tech_connector.services.licensing_startup_policy import (
            development_entitlement_bypass_allowed,
        )

        # Source-development bypass remains explicit and is never honored by a
        # frozen production build.
        self.require_entitlement = bool(require_entitlement) or not development_entitlement_bypass_allowed()
        shared_context = licensing_context
        if shared_context is None and ui_window is not None:
            shared_context = getattr(
                getattr(ui_window, "service", None),
                "licensing_context",
                None,
            )
        self.licensing_context = shared_context or LicensingContext.from_defaults(APP_DIR)
        self.commercial_use = bool(commercial_use)
        self.app_major_version = str(
            app_major_version
            or str(APP_VERSION).lstrip("vV").split(".", 1)[0]
        )
        self.command_router = command_router if command_router is not None else CommandRouter()
        self.runtime_kernel = runtime_kernel
        self.runtime_packages = tuple(runtime_packages or ())
        self._ui_window = ui_window
        self.dcc = DccAPINamespace(self)
        self.kingdom = GameEngineAPINamespace(self)
        self.game_engine = self.kingdom
        self.garden = SceneViewerAPINamespace(self)
        self.scene_viewer = self.garden
        self.ophanim = ImageEditorAPINamespace(self)
        self.image_editor = self.ophanim
        self.ui = UiAPINamespace(self, ui_window=self._ui_window)
        self.call_dcc_function = DccFunctionCaller(self)
        self.ai = AIAPINamespace(self)
        self.reasoning = ReasoningRuntimeNamespace(self)
        self.runtime = self.reasoning
        self.features = APIFeatureNamespace(self)

    def entitlement(self) -> LicenseEntitlement:
        signed_token = self._signed_entitlement_token()
        if signed_token:
            evaluation = self.licensing_context.evaluate(
                token=signed_token,
                project_root=self.project_root or None,
                product=self.licensing_context.configuration.product,
                app_major_version=self.app_major_version,
                commercial_use=self.commercial_use,
            )
            return entitlement_from_signed_evaluation(evaluation)
        return verify_entitlement(self.settings, secret=self.license_secret)

    def entitlement_status(self) -> dict[str, Any]:
        signed_token = self._signed_entitlement_token()
        if signed_token:
            return entitlement_status_from_entitlement(
                self.entitlement(),
                configured=True,
            )
        return entitlement_status_row(self.settings, secret=self.license_secret)

    def _signed_entitlement_token(self) -> str:
        token = self.licensing_context.token(
            str(self.settings.get("tech_connector_license_token") or "")
        )
        return token if token and not token.startswith(f"{LICENSE_TOKEN_PREFIX}.") else ""

    def _require_unlocked(self) -> LicenseEntitlement:
        entitlement = self.entitlement()
        if self.require_entitlement and not entitlement.unlocked:
            raise PermissionError(entitlement.reason or "Tech Connector license login is required.")
        if self.require_entitlement and "official_api_access" not in entitlement.capabilities:
            raise PermissionError("This license tier does not include official API access.")
        signed_token = self._signed_entitlement_token()
        if signed_token:
            try:
                from tech_connector.bridges.session_authorization import (
                    bridge_session_path_for_context,
                    ensure_bridge_session_for_evaluation,
                )

                evaluation = self.licensing_context.evaluate(
                    token=signed_token,
                    project_root=self.project_root or None,
                    product=self.licensing_context.configuration.product,
                    app_major_version=self.app_major_version,
                    commercial_use=self.commercial_use,
                )
                ensure_bridge_session_for_evaluation(
                    evaluation,
                    path=bridge_session_path_for_context(self.licensing_context),
                )
            except Exception:
                # Non-DCC API operations remain usable. A real DCC endpoint
                # independently rejects requests without the local capability.
                pass
        return entitlement

    def _tag(self, entitlement: LicenseEntitlement, *, operation: str = "", output_path: str | Path = "") -> dict[str, Any]:
        return build_usage_tag(
            entitlement,
            project_root=self.project_root,
            operation=operation,
            output_path=output_path,
        )

    def verify_license(self) -> dict[str, Any]:
        return self.entitlement_status()

    def attach_ui_window(self, ui_window: Any | None) -> None:
        self._ui_window = ui_window
        self.ui.attach_window(ui_window)
        self.features._populated = False

    def capabilities(self) -> dict[str, Any]:
        return self.reasoning.capabilities()

    def describe(self, feature_id: str = "", operation: str = "") -> dict[str, Any]:
        """Describe the API or one discoverable feature operation."""
        if feature_id:
            return self.features.describe(feature_id, operation)
        return {
            "schema": f"{API_SCHEMA}.help",
            "api_version": API_VERSION,
            "app_version": str(APP_VERSION),
            "namespaces": {
                "ai": "Provider-neutral model discovery, routing, benchmarking, and generation.",
                "reasoning": "Project-aware reasoning, runtime tools, and progress events.",
                "features": "Searchable capability catalog and generic invocation.",
                "dcc": "Maya, Blender, Unreal, Unity, Houdini, and other host operations.",
                "kingdom": "Game-engine authoring and runtime operations.",
                "garden": "DCC scene viewer and authoring operations.",
                "ophanim": "Image editor operations.",
                "ui": "Attached desktop UI actions.",
            },
            "aliases": {
                "runtime": "reasoning",
                "game_engine": "kingdom",
                "scene_viewer": "garden",
                "image_editor": "ophanim",
            },
            "discovery": {
                "search": "api.features.search('material')",
                "feature_help": "api.features.describe('ai.generate', 'generate')",
                "invoke": "api.features.invoke(feature_id, operation, **kwargs)",
            },
            "result_contract": {
                "check": "if result.ok",
                "serialize": "result.to_dict()",
                "raise_on_error": "result.unwrap()",
                "structured_error": "result.error_detail",
            },
        }

    def llm_queue_status(self) -> dict[str, Any]:
        """
            Returns process-wide LLM queue telemetry.
        :return: queue depth, capacity, counters, and request snapshots
        """
        return _llm_request_queue_snapshot()

    def cancel_llm_request(
        self,
        request_id: str,
        reason: str = "Cancelled by API request.",
    ) -> bool:
        """
            Cancels queued work or detaches from an active provider request.
        :param request_id: queue request correlation identifier
        :param reason: user-facing cancellation reason
        :return: whether an active request was found
        """
        return _cancel_llm_request(request_id, reason)

    def _populate_feature_registry(self, registry: APIFeatureRegistry) -> None:
        """Register public API modules plus each installed runtime adapter."""

        def add(
            feature_id: str,
            category: str,
            description: str,
            handlers: dict[str, Callable[..., Any]] | None = None,
            *,
            access: str = "direct",
            owner_feature_id: str = "",
            lifecycle_stage: str = "",
            stability: str = "stable",
            dependencies: tuple[str, ...] = (),
            permissions: tuple[str, ...] = (),
            source: str = "tech_connector.api",
            operation_schemas: dict[str, dict[str, Any]] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            operation_handlers = dict(handlers or {})
            registry.register(
                APIFeatureDescriptor(
                    feature_id=feature_id,
                    category=category,
                    version=API_VERSION,
                    description=description,
                    access=access,
                    owner_feature_id=owner_feature_id,
                    lifecycle_stage=lifecycle_stage,
                    stability=stability,
                    operations=tuple(operation_handlers),
                    dependencies=dependencies,
                    permissions=permissions,
                    source=source,
                    operation_schemas=dict(operation_schemas or {}),
                    metadata=dict(metadata or {}),
                ),
                operation_handlers,
            )

        def adapter_description(adapter: Any, adapter_name: str) -> str:
            lines = str(adapter.__class__.__doc__ or "").strip().splitlines()
            return lines[0] if lines else f"Runtime adapter: {adapter_name}."

        add(
            "api.discovery",
            "api",
            "Search features and inspect callable operation signatures before invocation.",
            {
                "search": self.features.search,
                "describe": self.features.describe,
                "manifest": self.features.manifest,
            },
            lifecycle_stage="discovery",
        )
        add(
            "reasoning.runtime",
            "reasoning",
            "Shared request preparation, reasoning, routing, and response runtime.",
            {
                "snapshot": self.reasoning.snapshot,
                "prepare": self.reasoning.prepare,
                "run": self.reasoning.run,
                "run_chain": self.reasoning.run_chain,
            },
            dependencies=("runtime.context", "runtime.validation"),
            lifecycle_stage="orchestration",
        )
        add(
            "ai.generate",
            "models",
            "List models, preview routing, and generate through one provider-neutral API.",
            {
                "models": self.ai.models,
                "local_recommendation": self.ai.local_recommendation,
                "benchmark_local": self.ai.benchmark_local,
                "route": self.ai.route,
                "generate": self.ai.generate,
            },
            dependencies=("reasoning.runtime",),
            lifecycle_stage="generation",
        )
        add(
            "reasoning.tools",
            "reasoning",
            "Registered runtime tool discovery and approval-aware execution.",
            {
                "list": self.reasoning.tools,
                "execute": self.reasoning.execute_tool,
            },
            permissions=("explicit_approval_for_mutation",),
            lifecycle_stage="execution",
        )
        add(
            "llm.queue",
            "reasoning",
            "Provider-aware LLM scheduling telemetry and targeted cancellation.",
            {
                "status": self.llm_queue_status,
                "cancel": self.cancel_llm_request,
            },
            dependencies=("reasoning.runtime",),
            lifecycle_stage="orchestration",
        )
        add(
            "planning.action_graph",
            "planning",
            "Natural-language action graph planning and execution.",
            {
                "plan": self.plan_prompt,
                "execute": self.execute_action_graph,
            },
            lifecycle_stage="planning",
        )
        add(
            "planning.prompt_chain",
            "planning",
            "Sequential prompt-chain planning and execution.",
            {
                "plan": self.plan_prompt_chain,
                "execute": self.execute_prompt_chain,
            },
            lifecycle_stage="planning",
        )
        add(
            "code.pipeline_generation",
            "code",
            "Generate pipeline Python from a planned prompt.",
            {"generate": self.generate_pipeline_from_prompt},
            dependencies=("planning.action_graph",),
            lifecycle_stage="generation",
        )
        add(
            "execution.python",
            "execution",
            "Execute an approved normal-Python callable.",
            {"call": self._invoke_python_feature},
            permissions=("official_api_access",),
            lifecycle_stage="execution",
        )
        add(
            "execution.dcc",
            "execution",
            "Execute a DCC callable through its host bridge.",
            {"call": self._invoke_dcc_feature},
            permissions=("official_api_access", "connected_dcc_bridge"),
            lifecycle_stage="execution",
        )
        add(
            "execution.game_engine",
            "execution",
            "Drive game-engine authoring, runtime setup, and graph execution in The Kingdom.",
            {
                "access_contract": self.kingdom.access_contract,
                "editor_capabilities": self.kingdom.editor_capabilities,
                "editor_describe": self.kingdom.editor_describe,
                "editor_call": self.kingdom.editor_call,
                "configure_runtime": self.kingdom.configure_runtime,
                "create_effect": self.kingdom.create_effect,
                "update_running_game": self.kingdom.update_running_game,
                "plan_playtest": self.kingdom.plan_playtest,
                "create_character": self.kingdom.create_character,
                "decide_character": self.kingdom.decide_character,
                "execute_world_intelligence": self.kingdom.execute_world_intelligence,
                "create_game_experience": self.kingdom.create_game_experience,
                "validate_game_experience": self.kingdom.validate_game_experience,
                "create_presentation": self.kingdom.create_presentation,
                "preview_presentation": self.kingdom.preview_presentation,
                "graph_to_code": self.kingdom.graph_to_code,
                "code_to_graph": self.kingdom.code_to_graph,
                "compile_graph": self.kingdom.compile_graph,
                "execute_graph": self.kingdom.execute_graph,
                "create_graph_runtime": self.kingdom.create_graph_runtime,
            },
            permissions=("official_api_access",),
            lifecycle_stage="execution",
            source="tech_connector.game_engine.runtime.tc_engine_api.engine",
        )
        add(
            "execution.scene_viewer",
            "execution",
            "Issue commands against the active scene viewer session and route adaptive scene graph operations.",
            {
                "commands": self.garden.commands,
                "route": self.garden.route,
                "execute": self.garden.execute_active,
                "target": self.garden.target,
                "target_from_proxy": self.garden.target_from_proxy,
                "active_viewer": self.garden.active_viewer,
                "register_active_viewer": self.garden.register_active_viewer,
                "unregister_active_viewer": self.garden.unregister_active_viewer,
            },
            permissions=("official_api_access", "connected_viewer_bridge"),
            lifecycle_stage="execution",
            source="tech_connector.viewer_cmds",
        )
        add(
            "interaction.image_editor",
            "interaction",
            "Capture DCC viewport buffers, open/save image documents, and launch Ophanim tabs.",
            {
                "capture_viewport": self.ophanim.capture_viewport,
                "open_image": self.ophanim.open_image,
                "capture_and_open": self.ophanim.capture_and_open,
            },
            permissions=("official_api_access",),
            lifecycle_stage="interaction",
            source="tech_connector.ui.image_editor_widget",
        )
        add(
            "interaction.ui",
            "interaction",
            "Execute desktop UI actions by name, stream the mirrored action catalog, and call discovered actions directly.",
            self.ui.feature_handlers(),
            permissions=("official_api_access",),
            lifecycle_stage="interaction",
            source="tech_connector.api",
        )
        add(
            "intelligence.dcc_catalog",
            "intelligence",
            "Discover current DCC API aliases and indexed functions.",
            {
                "catalog": self.dcc.catalog,
                "aliases": self.dcc.aliases,
            },
            lifecycle_stage="evidence",
        )
        add(
            "api.license",
            "api",
            "Inspect the current API entitlement.",
            {"status": self.verify_license},
            lifecycle_stage="access",
        )

        add(
            "understanding.request_frame",
            "understanding",
            "Deterministically classify request shape, host, scope, and constraints.",
            {"analyze": analyze_request_frame},
            lifecycle_stage="understanding",
            source="tech_connector.services.reasoning.request_frame_service.analyze_request_frame",
        )
        add(
            "prompt.resource_orchestration",
            "prompt",
            "Build a goal-aware resource and model-assignment policy.",
            {"plan": build_resource_orchestration_plan},
            lifecycle_stage="planning",
            source=(
                "tech_connector.services.prompt."
                "prompt_resource_orchestration_service.build_resource_orchestration_plan"
            ),
        )
        add(
            "context.conversation_workspace",
            "context",
            "Normalize a canonical conversation workspace into its compatibility snapshot.",
            {"snapshot": compatibility_snapshot},
            lifecycle_stage="context",
            source="tech_connector.services.conversation_workspace_service.compatibility_snapshot",
        )
        add(
            "quality.validation_plan",
            "quality",
            "Plan focused validation commands for the paths being changed.",
            {"plan": plan_validation_for_paths},
            lifecycle_stage="validation",
            source="tech_connector.services.validation_planner_service.plan_validation_for_paths",
        )
        add(
            "quality.validation_intent",
            "quality",
            "Classify explicit project-validation requests before execution.",
            {"classify": classify_validation_intent},
            lifecycle_stage="understanding",
            source=(
                "tech_connector.services.project_validation_intent_service."
                "classify_validation_intent"
            ),
        )
        add(
            "intelligence.tool_discovery",
            "intelligence",
            "Discover real callable symbols from project source without inventing targets.",
            {"list_internal": list_internal_functions},
            lifecycle_stage="evidence",
            source="tech_connector.services.tool_discovery_service.list_internal_functions",
        )

        owned_features = (
            (
                "prompt.stage_quality",
                "prompt",
                "Audit understanding, routing, and plan quality before generation.",
                "reasoning.runtime",
                "planning",
                "tech_connector.services.prompt.prompt_stage_quality_service.audit_prompt_stage_quality",
            ),
            (
                "planning.implementation_contract",
                "planning",
                "Enrich and verify per-symbol implementation plans and cross-file interfaces.",
                "code.project_edit_workflow",
                "planning",
                "tech_connector.services.implementation_plan_quality_service.enrich_implementation_plan",
            ),
            (
                "code.project_edit_workflow",
                "code",
                "Generate and converge one or many project files through scoped validation.",
                "reasoning.runtime",
                "generation",
                "tech_connector.services.project_edit_workflow_service.run_multi_file_project_edit_workflow",
            ),
            (
                "quality.project_edit_passes",
                "quality",
                "Run separate syntax, import, API, signal, dead-code, behavior, and final checks.",
                "code.project_edit_workflow",
                "validation",
                "tech_connector.services.project_edit_workflow_service",
            ),
            (
                "intelligence.project_index",
                "intelligence",
                "Maintain exact project-index updates and project-aware search evidence.",
                "reasoning.runtime",
                "evidence",
                "tech_connector.services.project_service.queue_project_index_updates",
            ),
            (
                "models.provider_routing",
                "models",
                "Resolve local or login-backed model providers and route inference.",
                "reasoning.runtime",
                "routing",
                "tech_connector.services.llm_router_service.resolve_llm_provider_route",
            ),
            (
                "models.inference_telemetry",
                "models",
                "Capture prompt, first-token, generation, token, and throughput metrics.",
                "reasoning.runtime",
                "telemetry",
                "tech_connector.services.llm_router_service.pop_last_inference_metrics",
            ),
            (
                "execution.adaptive_goals",
                "execution",
                "Track per-goal evidence, confidence, predictions, and observed outcomes.",
                "reasoning.runtime",
                "orchestration",
                "tech_connector.services.adaptive.execution_state.AdaptiveExecutionState",
            ),
            (
                "execution.supervised_actions",
                "execution",
                "Execute action graphs with cancellation, output references, and repair supervision.",
                "planning.action_graph",
                "execution",
                "tech_connector.services.action_execution_engine.ActionExecutionEngine",
            ),
            (
                "provenance.usage",
                "provenance",
                "Tag generated Python, projects, and sidecars with usage provenance.",
                "code.pipeline_generation",
                "completion",
                "tech_connector.services.usage_provenance_service",
            ),
        )
        for (
            feature_id,
            category,
            description,
            owner_feature_id,
            lifecycle_stage,
            source,
        ) in owned_features:
            add(
                feature_id,
                category,
                description,
                access="owned",
                owner_feature_id=owner_feature_id,
                lifecycle_stage=lifecycle_stage,
                source=source,
            )

        internal_features = (
            (
                "repair.symbol_chunks",
                "repair",
                "Enforce exact class/function repair boundaries and reject unchanged repairs.",
                "code.project_edit_workflow",
                "repair",
                "tech_connector.services.repair_prompt_enforcement_service",
            ),
            (
                "ui.pipeline_node_graph",
                "ui.pipeline",
                "Render and edit pipeline nodes, links, attributes, and smart tool menus.",
                "planning.action_graph",
                "interaction",
                "tech_connector.ui.pipeline_node_view",
            ),
            (
                "ui.pipeline_utility_nodes",
                "ui.pipeline",
                "Provide built-in dictionary, list, string, filesystem, and value nodes.",
                "planning.action_graph",
                "interaction",
                "tech_connector.ui.pipeline_utility_nodes",
            ),
        )
        for (
            feature_id,
            category,
            description,
            owner_feature_id,
            lifecycle_stage,
            source,
        ) in internal_features:
            add(
                feature_id,
                category,
                description,
                access="internal",
                owner_feature_id=owner_feature_id,
                lifecycle_stage=lifecycle_stage,
                stability="internal",
                source=source,
            )

        kernel = self.reasoning._kernel_instance()
        adapter_groups = [
            (
                "runtime.context",
                kernel.context_adapters,
                {
                    "active_context": "get_active_context",
                    "interaction_surface": "get_interaction_surface",
                    "permission_context": "get_permission_context",
                },
            ),
            (
                "runtime.reasoning",
                kernel.reasoning_adapters,
                {
                    "system_instructions": "get_system_instructions",
                    "prompt_overlays": "get_prompt_overlays",
                    "domain_vocabulary": "get_domain_vocabulary",
                },
            ),
            (
                "runtime.capability",
                kernel.capability_bridges,
                {"tools": "get_tools"},
            ),
            (
                "runtime.validation",
                kernel.validation_contracts,
                {
                    "preconditions": "validate_preconditions",
                    "plan": "validate_plan",
                    "execution_result": "validate_execution_result",
                    "side_effects": "validate_side_effects",
                    "completion": "validate_completion",
                },
            ),
            (
                "runtime.code_policy",
                kernel.code_intelligence_adapters,
                {"generation_policy": "get_generation_policy"},
            ),
            (
                "runtime.rules",
                kernel.rule_providers,
                {"rule_sets": "get_rule_sets"},
            ),
        ]
        for category, adapters, operation_methods in adapter_groups:
            for adapter in adapters:
                adapter_name = re.sub(
                    r"[^a-z0-9_.-]+",
                    "_",
                    str(getattr(adapter, "name", adapter.__class__.__name__)).lower(),
                ).strip("_")
                handlers = {
                    operation: getattr(adapter, method_name)
                    for operation, method_name in operation_methods.items()
                    if callable(getattr(adapter, method_name, None))
                }
                add(
                    f"{category}.{adapter_name}",
                    category,
                    adapter_description(adapter, adapter_name),
                    handlers,
                    lifecycle_stage="orchestration",
                    source=f"{adapter.__class__.__module__}.{adapter.__class__.__name__}",
                    metadata={"adapter_name": adapter_name},
                )

        passive_groups = [
            ("runtime.code_understanding", kernel.code_understanding_providers),
            ("runtime.knowledge", kernel.knowledge_sources),
            ("runtime.index", kernel.index_providers),
            ("runtime.symbol_lookup", kernel.symbol_lookup_providers),
            ("runtime.escalation", kernel.escalation_policies),
        ]
        for category, adapters in passive_groups:
            for adapter in adapters:
                adapter_name = re.sub(
                    r"[^a-z0-9_.-]+",
                    "_",
                    str(getattr(adapter, "name", adapter.__class__.__name__)).lower(),
                ).strip("_")
                registry.register(
                    APIFeatureDescriptor(
                        feature_id=f"{category}.{adapter_name}",
                        category=category,
                        version=API_VERSION,
                        description=adapter_description(adapter, adapter_name),
                        access="owned",
                        owner_feature_id="reasoning.runtime",
                        lifecycle_stage="evidence",
                        source=f"{adapter.__class__.__module__}.{adapter.__class__.__name__}",
                        metadata={"adapter_name": adapter_name},
                    )
                )

    def _invoke_python_feature(
        self,
        entry_point: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        **options: Any,
    ) -> APIResult:
        return self.call_function(
            entry_point,
            *(args or []),
            kwargs=kwargs,
            **options,
        )

    def _invoke_dcc_feature(
        self,
        entry_point: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        **options: Any,
    ) -> APIResult:
        return self._call_dcc_function_impl(
            entry_point,
            *(args or []),
            kwargs=kwargs,
            **options,
        )

    def plan_prompt(self, prompt: str, *, project_roots: list[str] | None = None) -> dict[str, Any]:
        self._require_unlocked()
        roots = list(project_roots or _project_roots(self.project_root, self.settings))
        return plan_prompt_to_action_graph(prompt, roots)

    def plan_prompt_chain(
        self,
        prompts: str | list[str] | tuple[str, ...],
        *,
        project_roots: list[str] | None = None,
    ) -> dict[str, Any]:
        """Plan a sequential prompt chain without executing it."""
        self._require_unlocked()
        steps = _normalize_prompt_chain(prompts)
        roots = list(project_roots or _project_roots(self.project_root, self.settings))
        planned_steps = []
        for index, prompt in enumerate(steps, start=1):
            graph = plan_prompt_to_action_graph(prompt, roots)
            planned_steps.append(
                {
                    "index": index,
                    "prompt": prompt,
                    "understanding": graph.get("goal") or graph.get("prompt") or prompt,
                    "intent": graph.get("intent") or "",
                    "confidence": graph.get("confidence"),
                    "graph": graph,
                }
            )
        return {
            "schema": "tech_connector.prompt_chain.v1",
            "ok": bool(planned_steps),
            "step_count": len(planned_steps),
            "steps": planned_steps,
        }

    def execute_action_graph(
        self,
        graph: dict[str, Any],
        *,
        approved: bool = False,
        dry_run: bool = False,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entitlement = self._require_unlocked()
        merged_policy = {
            "official_api": True,
            "license_tier": entitlement.tier,
            "original_prompt": graph.get("goal") or graph.get("prompt") or "",
            "pipeline_live_preflight": "required",
            **(policy or {}),
        }
        if self.project_root:
            merged_policy.setdefault("project_root", self.project_root)
        context = ExecutionContext(
            project_root=self.project_root,
            project_roots=_project_roots(self.project_root, self.settings),
            approved=approved,
            dry_run=dry_run,
            policy=merged_policy,
        )
        return ActionExecutionEngine(default_action_handler_registry()).execute_plan(graph, context)

    def execute_prompt_chain(
        self,
        prompts: str | list[str] | tuple[str, ...],
        *,
        approved: bool = False,
        dry_run: bool = False,
        stop_on_error: bool = True,
        policy: dict[str, Any] | None = None,
        project_roots: list[str] | None = None,
    ) -> APIResult:
        """Plan and execute a sequential natural-language prompt chain."""
        try:
            entitlement = self._require_unlocked()
            steps = _normalize_prompt_chain(prompts)
            if not steps:
                return APIResult(ok=False, error="Prompt chain is empty.", entitlement=entitlement.to_dict())
            roots = list(project_roots or _project_roots(self.project_root, self.settings))
            results = []
            stopped = False
            stop_reason = ""
            for index, prompt in enumerate(steps, start=1):
                graph = plan_prompt_to_action_graph(prompt, roots)
                step_policy = {
                    "prompt_chain": True,
                    "chain_index": index,
                    "chain_count": len(steps),
                    **(policy or {}),
                }
                report = self.execute_action_graph(
                    graph,
                    approved=approved,
                    dry_run=dry_run,
                    policy=step_policy,
                )
                success = _execution_report_succeeded(report)
                step_result = {
                    "index": index,
                    "prompt": prompt,
                    "understanding": graph.get("goal") or graph.get("prompt") or prompt,
                    "intent": graph.get("intent") or "",
                    "confidence": graph.get("confidence"),
                    "graph": graph,
                    "execution": report,
                    "ok": success,
                }
                results.append(step_result)
                if not success and stop_on_error:
                    stopped = True
                    stop_reason = f"Step {index} ended with status {report.get('status') or 'unknown'}."
                    break
            ok = len(results) == len(steps) and all(step.get("ok") for step in results)
            tag = self._tag(entitlement, operation="execute_prompt_chain")
            if self.project_root:
                write_project_provenance_marker(self.project_root, tag)
            return APIResult(
                ok=ok,
                result={
                    "schema": "tech_connector.prompt_chain_execution.v1",
                    "step_count": len(steps),
                    "completed_steps": len(results),
                    "stopped": stopped,
                    "stop_reason": stop_reason,
                    "steps": results,
                },
                error="" if ok else stop_reason or "One or more prompt chain steps failed.",
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def generate_pipeline_from_prompt(
        self,
        prompt: str,
        *,
        name: str = "headless_pipeline",
        stamp_provenance: bool = True,
    ) -> APIResult:
        try:
            entitlement = self._require_unlocked()
            graph = self.plan_prompt(prompt)
            workflow_plan = workflow_plan_from_action_graph(graph) or {}
            if not workflow_plan.get("success"):
                return APIResult(
                    ok=False,
                    error="Prompt did not resolve to a complete workflow plan.",
                    result={"graph": graph, "workflow_plan": workflow_plan},
                    entitlement=entitlement.to_dict(),
                )
            code = generate_pipeline_code_from_graph(
                name,
                prompt,
                workflow_plan.get("steps") or [],
                view=_WorkflowPlanView(workflow_plan),
            )
            tag = self._tag(entitlement, operation="generate_pipeline_from_prompt")
            if stamp_provenance:
                code = apply_python_provenance(code, tag)
            return APIResult(ok=True, result={"code": code, "graph": graph, "workflow_plan": workflow_plan}, entitlement=entitlement.to_dict(), provenance=tag)
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def call_function(
        self,
        entry_point: str,
        *args: Any,
        kwargs: dict[str, Any] | None = None,
        extra_roots: list[str] | None = None,
        stamp_project_provenance: bool = False,
    ) -> APIResult:
        """Call an approved Python function through the official API boundary."""
        try:
            entitlement = self._require_unlocked()
            roots = list(extra_roots or _project_roots(self.project_root, self.settings))
            fn = _import_callable(entry_point, extra_roots=roots)
            signature = str(inspect.signature(fn))
            result = fn(*args, **(kwargs or {}))
            tag = self._tag(entitlement, operation=f"call_function:{entry_point}")
            if stamp_project_provenance and self.project_root:
                write_project_provenance_marker(self.project_root, tag)
            return APIResult(
                ok=True,
                result={"value": result, "entry_point": entry_point, "signature": signature},
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def _call_dcc_function_impl(
        self,
        entry_point: str,
        *args: Any,
        host: str = "",
        kwargs: dict[str, Any] | None = None,
        stamp_project_provenance: bool = True,
    ) -> APIResult:
        """Call a DCC package function inside the target host process.

        This is the official API path for functions that require Maya, Unreal,
        Blender, MotionBuilder, Houdini, Substance Painter, or another host
        runtime. Unlike `call_function`, this does not import the target module
        in normal Python; it asks the host bridge to import and run it in the DCC.
        """
        try:
            entitlement = self._require_unlocked()
            host_key = _normalize_host(host)
            fn_args = list(args)
            fn_kwargs = dict(kwargs or {})
            router = self.command_router
            if not host_key and hasattr(router, "host_for_tool_function"):
                host_key = str(router.host_for_tool_function(entry_point) or "")
            if host_key:
                ok, output = self._call_dcc_bridge_function(host_key, entry_point, fn_args, fn_kwargs)
                label = f"{host_key.replace('_', ' ').title()} Function"
            else:
                payload = {"function": entry_point, "args": fn_args, "kwargs": fn_kwargs}
                label, ok, output = router.execute_tool_function_from_text(json.dumps(payload))
            tag = self._tag(entitlement, operation=f"call_dcc_function:{entry_point}")
            if stamp_project_provenance and self.project_root:
                write_project_provenance_marker(self.project_root, tag)
            return APIResult(
                ok=bool(ok),
                result={"label": label, "host": host_key, "entry_point": entry_point, "output": output},
                error="" if ok else str(output),
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(ok=False, error=str(exc))

    def _call_dcc_bridge_function(
        self,
        host: str,
        entry_point: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> tuple[bool, str]:
        router = self.command_router
        host = _normalize_host(host)
        if host == "unreal":
            bridge = getattr(router, "unreal", None)
            if bridge and hasattr(bridge, "call"):
                return bridge.call(entry_point, args=args, kwargs=kwargs)
        bridge = None
        if hasattr(router, "_host_bridge_for_operation"):
            bridge = router._host_bridge_for_operation(host)
        if bridge and hasattr(bridge, "call_function"):
            return bridge.call_function(entry_point, args=args, kwargs=kwargs)
        if hasattr(router, "execute_tool_function_from_text"):
            import json

            label, ok, output = router.execute_tool_function_from_text(
                json.dumps({"function": entry_point, "args": args, "kwargs": kwargs})
            )
            return bool(ok), str(output)
        return False, f"No DCC bridge call function is configured for host: {host}"

    def dry_run_prompt(self, prompt: str) -> dict[str, Any]:
        graph = self.plan_prompt(prompt)
        return self.execute_action_graph(graph, dry_run=True)


class DccHostAPINamespace:
    """Dynamic host namespace for official DCC API aliases."""

    def __init__(self, api: TechConnectorHeadlessAPI, host: str) -> None:
        self._api = api
        self._host = _normalize_host(host)

    def aliases(self) -> dict[str, str]:
        return dict(DCC_API_ALIASES.get(self._host, {}))

    def resolve(self, name: str) -> str:
        key = _normalize_api_name(name)
        aliases = DCC_API_ALIASES.get(self._host, {})
        if key in aliases:
            return aliases[key]
        if "." in str(name):
            return str(name)
        from tech_connector.services.api_catalog_service import resolve_dcc_api_name

        return resolve_dcc_api_name(self._host, str(name), aliases=DCC_API_ALIASES)

    def call(self, name: str, *args: Any, kwargs: dict[str, Any] | None = None, **options: Any) -> APIResult:
        entry_point = self.resolve(name)
        return self._api._call_dcc_function_impl(
            entry_point,
            *args,
            host=self._host,
            kwargs=kwargs,
            stamp_project_provenance=bool(options.pop("stamp_project_provenance", True)),
        )

    def __getattr__(self, name: str) -> Callable[..., APIResult]:
        if name.startswith("_"):
            raise AttributeError(name)

        def _caller(*args: Any, **kwargs: Any) -> APIResult:
            api_kwargs = kwargs.pop("kwargs", None)
            call_kwargs = dict(api_kwargs or {})
            call_kwargs.update(kwargs)
            return self.call(name, *args, kwargs=call_kwargs)

        _caller.__name__ = name
        return _caller


class DccAPINamespace:
    """Root namespace for DCC-specific official API calls."""

    def __init__(self, api: TechConnectorHeadlessAPI) -> None:
        self._api = api
        self.maya = DccHostAPINamespace(api, "maya")
        self.unreal = DccHostAPINamespace(api, "unreal")
        self.blender = DccHostAPINamespace(api, "blender")
        self.motionbuilder = DccHostAPINamespace(api, "motionbuilder")
        self.substance_painter = DccHostAPINamespace(api, "substance_painter")
        self.houdini = DccHostAPINamespace(api, "houdini")
        self.unity = DccHostAPINamespace(api, "unity")

    def host(self, host: str) -> DccHostAPINamespace:
        return DccHostAPINamespace(self._api, host)

    def aliases(self) -> dict[str, dict[str, str]]:
        return {host: dict(items) for host, items in DCC_API_ALIASES.items()}

    def catalog(self) -> dict[str, Any]:
        from tech_connector.services.api_catalog_service import discover_dcc_api_catalog

        return discover_dcc_api_catalog(aliases=DCC_API_ALIASES)


class DccFunctionCaller:
    """Callable namespace supporting both call_dcc_function(...) and host aliases."""

    def __init__(self, api: TechConnectorHeadlessAPI) -> None:
        self._api = api
        self.maya = DccHostAPINamespace(api, "maya")
        self.unreal = DccHostAPINamespace(api, "unreal")
        self.blender = DccHostAPINamespace(api, "blender")
        self.motionbuilder = DccHostAPINamespace(api, "motionbuilder")
        self.substance_painter = DccHostAPINamespace(api, "substance_painter")
        self.houdini = DccHostAPINamespace(api, "houdini")
        self.unity = DccHostAPINamespace(api, "unity")

    def __call__(self, entry_point: str, *args: Any, **kwargs: Any) -> APIResult:
        return self._api._call_dcc_function_impl(entry_point, *args, **kwargs)

    def host(self, host: str) -> DccHostAPINamespace:
        return DccHostAPINamespace(self._api, host)

    def aliases(self) -> dict[str, dict[str, str]]:
        return self._api.dcc.aliases()


class GameEngineAPINamespace:
    """High-level namespace for The Kingdom / game-engine operations."""

    def __init__(self, api: TechConnectorHeadlessAPI) -> None:
        self._api = api
        self._editor_api_instance: Any | None = None

    def _run(self, operation: str, action: Callable[[], Any], *, schema: str) -> APIResult:
        entitlement = None
        try:
            entitlement = self._api._require_unlocked()
            result = action()
            tag = self._api._tag(entitlement, operation=operation)
            if self._api.project_root:
                write_project_provenance_marker(self._api.project_root, tag)
            return APIResult(
                ok=True,
                result={
                    "schema": schema,
                    "operation": operation,
                    "value": _serialize_public_value(result),
                },
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(
                ok=False,
                error=str(exc),
                entitlement=entitlement.to_dict() if entitlement is not None else None,
            )

    def _engine(self):
        from tech_connector.game_engine.runtime import tc_engine_api

        return tc_engine_api.engine

    def _access_contract(self):
        from tech_connector.game_engine.runtime.tc_engine_api import engine_access_contract

        return engine_access_contract()

    def _editor_api(self):
        if not self._api.project_root:
            raise ValueError("project_root is required for Kingdom editor operations.")
        if self._editor_api_instance is None:
            from tech_connector.game_engine.assets import open_editor_api

            self._editor_api_instance = open_editor_api(self._api.project_root)
        return self._editor_api_instance

    @staticmethod
    def _editor_operation_names(editor: Any) -> tuple[str, ...]:
        contract = editor.capability_contract()
        names = {
            str(operation)
            for key, operations in contract.items()
            if key.endswith("_operations") and isinstance(operations, (list, tuple))
            for operation in operations
        }
        return tuple(sorted(names))

    def editor_capabilities(self) -> APIResult:
        """List the complete asset, level, build, and production editor contract."""
        return self._run(
            "kingdom.editor_capabilities",
            lambda: self._editor_api().capability_contract(),
            schema=f"{API_SCHEMA}.game_engine.editor_capabilities",
        )

    def editor_describe(self, operation: str = "") -> APIResult:
        """Inspect a Kingdom editor operation signature before calling it."""
        def _describe() -> dict[str, Any]:
            editor = self._editor_api()
            names = self._editor_operation_names(editor)
            requested = str(operation or "").strip()
            if requested and requested not in names:
                raise KeyError(f"Unknown Kingdom editor operation: {requested}")
            selected = (requested,) if requested else names
            rows = []
            for name in selected:
                handler = getattr(editor, name, None)
                if not callable(handler):
                    continue
                rows.append({
                    "name": name,
                    "signature": str(inspect.signature(handler)),
                    "documentation": inspect.getdoc(handler) or "",
                })
            return {"operation_count": len(rows), "operations": rows}

        return self._run(
            "kingdom.editor_describe",
            _describe,
            schema=f"{API_SCHEMA}.game_engine.editor_help",
        )

    def editor_call(self, operation: str, **kwargs: Any) -> APIResult:
        """Invoke a declared Kingdom editor operation with keyword arguments."""
        requested = str(operation or "").strip()

        def _invoke() -> Any:
            editor = self._editor_api()
            if requested not in self._editor_operation_names(editor):
                raise KeyError(f"Unknown Kingdom editor operation: {requested}")
            handler = getattr(editor, requested, None)
            if not callable(handler):
                raise RuntimeError(f"Kingdom editor operation is unavailable: {requested}")
            return handler(**dict(kwargs))

        return self._run(
            f"kingdom.editor_call:{requested or 'unknown'}",
            _invoke,
            schema=f"{API_SCHEMA}.game_engine.editor_result",
        )

    def access_contract(self) -> APIResult:
        return self._run(
            "kingdom.access_contract",
            lambda: self._access_contract(),
            schema=f"{API_SCHEMA}.game_engine_access_contract",
        )

    def configure_runtime(
        self,
        world: Any,
        *,
        target: str = "desktop",
        goal: str = "balanced",
        quality: str = "auto",
        backend: str = "auto",
        adaptive: bool = True,
        tick_rate: int | None = None,
    ) -> APIResult:
        return self._run(
            "kingdom.configure_runtime",
            lambda: self._engine().configure_runtime(
                world,
                target=target,
                goal=goal,
                quality=quality,
                backend=backend,
                adaptive=adaptive,
                tick_rate=tick_rate,
            ),
            schema=f"{API_SCHEMA}.game_engine.configure_runtime",
        )

    def create_effect(
        self,
        preset: str,
        *,
        target: str = "desktop",
        goal: str = "balanced",
        quality: str = "auto",
        seed: int = 1,
    ) -> APIResult:
        return self._run(
            "kingdom.create_effect",
            lambda: self._engine().create_effect(
                preset,
                target=target,
                goal=goal,
                quality=quality,
                seed=seed,
            ),
            schema=f"{API_SCHEMA}.game_engine.create_effect",
        )

    def update_running_game(
        self,
        scene_document: Any,
        scene_path: str | Path,
        *,
        force_full: bool = False,
    ) -> APIResult:
        return self._run(
            "kingdom.update_running_game",
            lambda: self._engine().update_running_game(
                scene_document,
                scene_path,
                force_full=force_full,
            ),
            schema=f"{API_SCHEMA}.game_engine.update_running_game",
        )

    def plan_playtest(
        self,
        *,
        target: str = "desktop",
        session_mode: str = "play_in_editor",
        changed_modes: list[str] | tuple[str, ...] = (),
        session_connected: bool = False,
    ) -> APIResult:
        return self._run(
            "kingdom.plan_playtest",
            lambda: self._engine().plan_playtest(
                target=target,
                session_mode=session_mode,
                changed_modes=changed_modes,
                session_connected=session_connected,
            ),
            schema=f"{API_SCHEMA}.game_engine.plan_playtest",
        )

    def create_character(self, world: Any, profile: Any) -> APIResult:
        return self._run(
            "kingdom.create_character",
            lambda: self._engine().create_character(world, profile),
            schema=f"{API_SCHEMA}.game_engine.create_character",
        )

    def decide_character(
        self,
        world: Any,
        character_id: str,
        actions: Any,
        *,
        available_affordances: Any = (),
        now: float = 0.0,
        model_proposal: Any = None,
    ) -> APIResult:
        return self._run(
            "kingdom.decide_character",
            lambda: self._engine().decide_character(
                world,
                character_id,
                actions,
                available_affordances=available_affordances,
                now=now,
                model_proposal=model_proposal,
            ),
            schema=f"{API_SCHEMA}.game_engine.decide_character",
        )

    def execute_world_intelligence(
        self,
        world: Any,
        runtime_state: Any,
        command: str,
        **payload: Any,
    ) -> APIResult:
        return self._run(
            "kingdom.execute_world_intelligence",
            lambda: self._engine().execute_world_intelligence(world, runtime_state, command, **payload),
            schema=f"{API_SCHEMA}.game_engine.execute_world_intelligence",
        )

    def create_game_experience(self, profile_id: str, game_types: Any, **options: Any) -> APIResult:
        return self._run(
            "kingdom.create_game_experience",
            lambda: self._engine().create_game_experience(profile_id, game_types, **options),
            schema=f"{API_SCHEMA}.game_engine.create_game_experience",
        )

    def validate_game_experience(self, profile: Any) -> APIResult:
        return self._run(
            "kingdom.validate_game_experience",
            lambda: self._engine().validate_game_experience(profile),
            schema=f"{API_SCHEMA}.game_engine.validate_game_experience",
        )

    def create_presentation(self, profile_id: str, visual_style: str, **options: Any) -> APIResult:
        return self._run(
            "kingdom.create_presentation",
            lambda: self._engine().create_presentation(profile_id, visual_style, **options),
            schema=f"{API_SCHEMA}.game_engine.create_presentation",
        )

    def preview_presentation(self, profile: Any, **options: Any) -> APIResult:
        return self._run(
            "kingdom.preview_presentation",
            lambda: self._engine().preview_presentation(profile, **options),
            schema=f"{API_SCHEMA}.game_engine.preview_presentation",
        )

    def graph_to_code(self, program: Any) -> APIResult:
        return self._run(
            "kingdom.graph_to_code",
            lambda: self._engine().graph_to_code(program),
            schema=f"{API_SCHEMA}.game_engine.graph_to_code",
        )

    def code_to_graph(self, source_code: str, previous: Any = None) -> APIResult:
        return self._run(
            "kingdom.code_to_graph",
            lambda: self._engine().code_to_graph(source_code, previous=previous),
            schema=f"{API_SCHEMA}.game_engine.code_to_graph",
        )

    def compile_graph(self, program_or_manifest: Any) -> APIResult:
        return self._run(
            "kingdom.compile_graph",
            lambda: self._engine().compile_graph(program_or_manifest),
            schema=f"{API_SCHEMA}.game_engine.compile_graph",
        )

    def execute_graph(self, program_or_manifest: Any, context: Any, **options: Any) -> APIResult:
        return self._run(
            "kingdom.execute_graph",
            lambda: self._engine().execute_graph(program_or_manifest, context, **options),
            schema=f"{API_SCHEMA}.game_engine.execute_graph",
        )

    def create_graph_runtime(self, program_or_manifest: Any, context: Any, **options: Any) -> APIResult:
        return self._run(
            "kingdom.create_graph_runtime",
            lambda: self._engine().create_graph_runtime(program_or_manifest, context, **options),
            schema=f"{API_SCHEMA}.game_engine.create_graph_runtime",
        )


class SceneViewerAPINamespace:
    """High-level namespace for The Garden / live scene command operations."""

    def __init__(self, api: TechConnectorHeadlessAPI) -> None:
        self._api = api

    def _run(self, operation: str, action: Callable[[], Any], *, schema: str) -> APIResult:
        entitlement = None
        try:
            entitlement = self._api._require_unlocked()
            result = action()
            tag = self._api._tag(entitlement, operation=operation)
            if self._api.project_root:
                write_project_provenance_marker(self._api.project_root, tag)
            return APIResult(
                ok=True,
                result={
                    "schema": schema,
                    "operation": operation,
                    "value": _serialize_public_value(result),
                },
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(
                ok=False,
                error=str(exc),
                entitlement=entitlement.to_dict() if entitlement is not None else None,
            )

    def _viewer(self):
        from tech_connector import viewer_cmds
        return viewer_cmds

    def commands(self) -> APIResult:
        return self._run(
            "garden.commands",
            lambda: self._viewer().commands(),
            schema=f"{API_SCHEMA}.scene_viewer.commands",
        )

    def route(self, command: str, command_target: Any, **kwargs: Any) -> APIResult:
        return self._run(
            "garden.route",
            lambda: self._viewer().route(command, command_target, **kwargs),
            schema=f"{API_SCHEMA}.scene_viewer.route",
        )

    def execute_active(self, command: str, **kwargs: Any) -> APIResult:
        return self._run(
            "garden.execute_active",
            lambda: self._viewer().execute_active(command, **kwargs),
            schema=f"{API_SCHEMA}.scene_viewer.execute_active",
        )

    def target(self, *args: Any, **kwargs: Any) -> APIResult:
        return self._run(
            "garden.target",
            lambda: self._viewer().target(*args, **kwargs),
            schema=f"{API_SCHEMA}.scene_viewer.target",
        )

    def target_from_proxy(self, *args: Any, **kwargs: Any) -> APIResult:
        return self._run(
            "garden.target_from_proxy",
            lambda: self._viewer().target_from_proxy(*args, **kwargs),
            schema=f"{API_SCHEMA}.scene_viewer.target_from_proxy",
        )

    def active_viewer(self) -> APIResult:
        def _snapshot() -> dict[str, Any]:
            viewer_payload = self.active_viewer_payload()
            return {
                "viewer": viewer_payload,
                "has_active_viewer": bool(viewer_payload),
            }

        return self._run(
            "garden.active_viewer",
            _snapshot,
            schema=f"{API_SCHEMA}.scene_viewer.active_viewer",
        )

    def active_viewer_payload(self) -> Any:
        from tech_connector.game_engine.integration.active_viewer_command_service import active_viewer as _active_viewer

        viewer = _active_viewer()
        if viewer is None:
            return None
        return {
            "type": viewer.__class__.__name__,
            "module": viewer.__class__.__module__,
            "repr": str(viewer),
        }

    def register_active_viewer(self, viewer: Any) -> APIResult:
        def _run_register() -> dict[str, Any]:
            from tech_connector.game_engine.integration.active_viewer_command_service import register_active_viewer

            register_active_viewer(viewer)
            return {"registered": True}

        return self._run(
            "garden.register_active_viewer",
            _run_register,
            schema=f"{API_SCHEMA}.scene_viewer.register_active_viewer",
        )

    def unregister_active_viewer(self, viewer: Any) -> APIResult:
        def _run_unregister() -> dict[str, Any]:
            from tech_connector.game_engine.integration.active_viewer_command_service import unregister_active_viewer

            unregister_active_viewer(viewer)
            return {"unregistered": True}

        return self._run(
            "garden.unregister_active_viewer",
            _run_unregister,
            schema=f"{API_SCHEMA}.scene_viewer.unregister_active_viewer",
        )


class ImageEditorAPINamespace:
    """High-level namespace for Ophanim image-editor and viewport capture tooling."""

    def __init__(self, api: TechConnectorHeadlessAPI) -> None:
        self._api = api

    def _run(self, operation: str, action: Callable[[], Any], *, schema: str) -> APIResult:
        entitlement = None
        try:
            entitlement = self._api._require_unlocked()
            result = action()
            tag = self._api._tag(entitlement, operation=operation)
            if self._api.project_root:
                write_project_provenance_marker(self._api.project_root, tag)
            return APIResult(
                ok=True,
                result={
                    "schema": schema,
                    "operation": operation,
                    "value": _serialize_public_value(result),
                },
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(
                ok=False,
                error=str(exc),
                entitlement=entitlement.to_dict() if entitlement is not None else None,
            )

    def _editor(self):
        from tech_connector.ui.image_editor_widget import ImageEditorWindow

        return ImageEditorWindow

    def capture_viewport(self, dcc_name: str = "Autodesk Maya", *, as_data_url: bool = True, return_path: bool = False) -> APIResult:
        def _capture() -> dict[str, Any]:
            from pathlib import Path
            from PySide6.QtCore import QByteArray, QBuffer, QIODevice
            import base64
            import tempfile
            from tech_connector.ui.image_editor_widget import capture_dcc_viewport_to_image

            qimg = capture_dcc_viewport_to_image(dcc_name)
            if qimg is None or qimg.isNull():
                return {"ok": False, "error": f"Viewport capture returned empty image for {dcc_name}."}
            result: dict[str, Any] = {
                "width": int(qimg.width()),
                "height": int(qimg.height()),
                "format": str(qimg.format()),
            }
            if return_path:
                path = Path(tempfile.gettempdir()) / f"tc_ophanim_capture_{int(time.time()*1000)}.png"
                if qimg.save(str(path), "PNG"):
                    result.update({"path": str(path), "saved": True})
                else:
                    result.update({"saved": False, "path": str(path)})
            if as_data_url:
                ba = QByteArray()
                buffer = QBuffer(ba)
                buffer.open(QIODevice.WriteOnly)
                qimg.save(buffer, "PNG")
                result["data_url"] = "data:image/png;base64," + base64.b64encode(ba.data()).decode("ascii")
                result["ok"] = True
            else:
                result["ok"] = True
            return result

        return self._run(
            "ophanim.capture_viewport",
            _capture,
            schema=f"{API_SCHEMA}.ophanim.capture_viewport",
        )

    def open_image(self, image_path: str = "", *, show: bool = True) -> APIResult:
        def _open() -> dict[str, Any]:
            editor = self._editor().open_for_image(image_path)
            if show:
                if not editor.isVisible():
                    editor.show()
                editor.raise_()
                editor.activateWindow()
            result: dict[str, Any] = {
                "opened": bool(editor),
                "window_id": id(editor),
                "image_path": str(image_path or ""),
            }
            if show:
                result["visible"] = bool(editor.isVisible())
            return result

        return self._run(
            "ophanim.open_image",
            _open,
            schema=f"{API_SCHEMA}.ophanim.open_image",
        )

    def capture_and_open(self, dcc_name: str = "Autodesk Maya") -> APIResult:
        def _open_capture() -> dict[str, Any]:
            from tech_connector.ui.image_editor_widget import capture_dcc_viewport_to_image

            qimg = capture_dcc_viewport_to_image(dcc_name)
            if qimg is None or qimg.isNull():
                return {"ok": False, "error": f"Viewport capture returned empty image for {dcc_name}."}
            editor = self._editor()
            win = editor._instances[-1] if editor._instances else editor.open_for_image("")
            now = int(time.time())
            if hasattr(win, "add_new_canvas_tab"):
                win.add_new_canvas_tab(title=f"Capture_{dcc_name.replace(' ', '')}_{now}.png", qimage=qimg)
                win.show()
                win.raise_()
                win.activateWindow()
            return {
                "ok": True,
                "dcc_name": dcc_name,
                "window_id": id(win),
            }

        return self._run(
            "ophanim.capture_and_open",
            _open_capture,
            schema=f"{API_SCHEMA}.ophanim.capture_and_open",
        )


class UiAPINamespace:
    """Mirror the attached desktop UI action surface through API calls."""

    _MODULE_PREFIX = "tech_connector.app."

    def __init__(self, api: TechConnectorHeadlessAPI, ui_window: Any | None = None) -> None:
        self._api = api
        self._ui_window = ui_window

    def attach_window(self, ui_window: Any | None) -> None:
        self._ui_window = ui_window

    def _run(self, operation: str, action: Callable[[], Any], *, schema: str) -> APIResult:
        entitlement = None
        try:
            entitlement = self._api._require_unlocked()
            result = action()
            tag = self._api._tag(entitlement, operation=operation)
            if self._api.project_root:
                write_project_provenance_marker(self._api.project_root, tag)
            return APIResult(
                ok=True,
                result={
                    "schema": schema,
                    "operation": operation,
                    "value": _serialize_public_value(result),
                },
                entitlement=entitlement.to_dict(),
                provenance=tag,
            )
        except Exception as exc:
            return APIResult(
                ok=False,
                error=str(exc),
                entitlement=entitlement.to_dict() if entitlement is not None else None,
            )

    def _require_window(self) -> Any:
        if self._ui_window is None:
            raise RuntimeError("No UI window is attached to this API instance.")
        return self._ui_window

    def _action_names(self) -> list[str]:
        window = self._ui_window
        if window is None:
            return []

        names: list[str] = []
        seen: set[str] = set()
        for name in dir(window):
            if not name or name.startswith("_"):
                continue
            attr = getattr(window, name, None)
            if not callable(attr):
                continue
            module = str(getattr(attr, "__module__", ""))
            if not module.startswith(self._MODULE_PREFIX):
                continue
            qualname = str(getattr(attr, "__qualname__", ""))
            if "." not in qualname:
                continue
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        names.sort()
        return names

    def _action_handler(self, action: str) -> Callable[..., APIResult]:
        def _invoke(*args: Any, **kwargs: Any) -> APIResult:
            return self.invoke(action, *args, **kwargs)

        _invoke.__name__ = action
        return _invoke

    def feature_handlers(self) -> dict[str, Callable[..., Any]]:
        handlers: dict[str, Callable[..., Any]] = {
            "catalog": self.catalog,
            "actions": self.actions,
            "invoke": self.invoke,
        }
        for action in self._action_names():
            handlers[action] = self._action_handler(action)
        return handlers

    def catalog(self) -> APIResult:
        return self._run(
            "ui.catalog",
            lambda: {
                "attached": bool(self._ui_window),
                "actions": self._action_names(),
            },
            schema=f"{API_SCHEMA}.ui.catalog",
        )

    def actions(self) -> APIResult:
        return self.catalog()

    def invoke(self, action: str, *args: Any, **kwargs: Any) -> APIResult:
        action = str(action or "").strip()
        if not action:
            return APIResult(ok=False, error="UI action is required.")

        def _invoke_action() -> Any:
            window = self._require_window()
            method = getattr(window, action, None)
            if method is None or not callable(method):
                raise AttributeError(f"UI action not found: {action}")
            return method(*args, **kwargs)

        return self._run(
            f"ui.invoke:{action}",
            _invoke_action,
            schema=f"{API_SCHEMA}.ui.invoke",
        )

    def __getattr__(self, name: str) -> Callable[..., APIResult]:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in ("catalog", "actions", "invoke", "feature_handlers"):
            raise AttributeError(name)
        if name in self._action_names():

            def _caller(*args: Any, **kwargs: Any) -> APIResult:
                return self.invoke(name, *args, **kwargs)

            _caller.__name__ = name
            return _caller
        raise AttributeError(name)


def create_api(**kwargs: Any) -> TechConnectorHeadlessAPI:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    return TechConnectorHeadlessAPI(**kwargs)


def llm_queue_status() -> dict[str, Any]:
    """
        Returns process-wide LLM queue telemetry.
    :return: queue depth, capacity, counters, and request snapshots
    """
    return _llm_request_queue_snapshot()


def cancel_llm_request(
    request_id: str,
    reason: str = "Cancelled by API request.",
) -> bool:
    """
        Cancels queued work or detaches from an active provider request.
    :param request_id: queue request correlation identifier
    :param reason: user-facing cancellation reason
    :return: whether an active request was found
    """
    return _cancel_llm_request(request_id, reason)


def verify_license(settings: dict[str, Any] | None = None, *, license_secret: str | None = None) -> dict[str, Any]:
    return TechConnectorHeadlessAPI(settings=settings, license_secret=license_secret, require_entitlement=False).verify_license()


def plan_prompt(prompt: str, **kwargs: Any) -> dict[str, Any]:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    return TechConnectorHeadlessAPI(**kwargs).plan_prompt(prompt)


def plan_prompt_chain(prompts: str | list[str] | tuple[str, ...], **kwargs: Any) -> dict[str, Any]:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    return TechConnectorHeadlessAPI(**kwargs).plan_prompt_chain(prompts)


def execute_action_graph(graph: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api = TechConnectorHeadlessAPI(
        settings=kwargs.pop("settings", None),
        project_root=kwargs.pop("project_root", None),
        license_secret=kwargs.pop("license_secret", None),
        require_entitlement=kwargs.pop("require_entitlement", True),
        ui_window=kwargs.pop("ui_window", None),
        licensing_context=kwargs.pop("licensing_context", None),
        commercial_use=kwargs.pop("commercial_use", True),
        app_major_version=kwargs.pop("app_major_version", None),
    )
    return api.execute_action_graph(graph, **kwargs)


def execute_prompt_chain(prompts: str | list[str] | tuple[str, ...], **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api = TechConnectorHeadlessAPI(
        settings=kwargs.pop("settings", None),
        project_root=kwargs.pop("project_root", None),
        license_secret=kwargs.pop("license_secret", None),
        require_entitlement=kwargs.pop("require_entitlement", True),
        command_router=kwargs.pop("command_router", None),
        ui_window=kwargs.pop("ui_window", None),
        licensing_context=kwargs.pop("licensing_context", None),
        commercial_use=kwargs.pop("commercial_use", True),
        app_major_version=kwargs.pop("app_major_version", None),
    )
    return api.execute_prompt_chain(prompts, **kwargs)


def call_function(entry_point: str, *args: Any, **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs.keys())
        if key in {
            "settings", "project_root", "license_secret", "require_entitlement", "ui_window",
            "licensing_context", "commercial_use", "app_major_version",
        }
    }
    call_kwargs = kwargs.pop("kwargs", None)
    return TechConnectorHeadlessAPI(**api_kwargs).call_function(entry_point, *args, kwargs=call_kwargs, **kwargs)


def call_dcc_function(entry_point: str, *args: Any, **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs.keys())
        if key in {
            "settings", "project_root", "license_secret", "require_entitlement",
            "command_router", "ui_window", "licensing_context", "commercial_use",
            "app_major_version",
        }
    }
    call_kwargs = kwargs.pop("kwargs", None)
    return TechConnectorHeadlessAPI(**api_kwargs).call_dcc_function(entry_point, *args, kwargs=call_kwargs, **kwargs)


def _reasoning_api_from_kwargs(kwargs: dict[str, Any]) -> TechConnectorHeadlessAPI:
    kwargs = dict(kwargs)
    if "ui_window" not in kwargs:
        kwargs["ui_window"] = get_default_ui_window()
    api_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs.keys())
        if key in {
            "settings",
            "project_root",
            "license_secret",
            "require_entitlement",
            "command_router",
            "runtime_kernel",
            "runtime_packages",
            "ui_window",
            "licensing_context",
            "commercial_use",
            "app_major_version",
        }
    }
    return TechConnectorHeadlessAPI(**api_kwargs)


def reasoning_capabilities(**kwargs: Any) -> dict[str, Any]:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    return _reasoning_api_from_kwargs(kwargs).reasoning.capabilities()


def reasoning_snapshot(prompt: str = "", **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.snapshot(prompt, context=kwargs.pop("context", None))


def prepare_reasoning_request(prompt: str, **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.prepare(prompt, context=kwargs.pop("context", None))


def run_reasoning(prompt: str, **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.run(
        prompt,
        context=kwargs.pop("context", None),
        progress_callback=kwargs.pop("progress_callback", None),
        activity_callback=kwargs.pop("activity_callback", None),
    )


def run_reasoning_chain(prompts: str | list[str] | tuple[str, ...], **kwargs: Any) -> APIResult:
    if "ui_window" not in kwargs:
        kwargs = dict(kwargs)
        kwargs["ui_window"] = get_default_ui_window()
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.run_chain(
        prompts,
        context=kwargs.pop("context", None),
        stop_on_error=kwargs.pop("stop_on_error", True),
        progress_callback=kwargs.pop("progress_callback", None),
        activity_callback=kwargs.pop("activity_callback", None),
    )


reason = run_reasoning


def list_runtime_tools(**kwargs: Any) -> APIResult:
    return _reasoning_api_from_kwargs(kwargs).reasoning.tools()


def execute_runtime_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> APIResult:
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.execute_tool(
        tool_name,
        arguments,
        approved=bool(kwargs.pop("approved", False)),
        dry_run=bool(kwargs.pop("dry_run", False)),
    )
