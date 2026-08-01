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
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from tech_connector.models.constants import APP_ROOT
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
from tech_connector.services.license_entitlement_service import LicenseEntitlement, entitlement_status_row, verify_entitlement
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "entitlement": self.entitlement or {},
            "provenance": self.provenance or {},
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
    if project_root:
        roots.append(str(Path(project_root).expanduser().resolve()))
    active = str(settings.get("active_project") or "").strip()
    if active and active not in roots:
        roots.append(active)
    tools = str(APP_ROOT.parent)
    if tools not in roots:
        roots.append(tools)
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
    ) -> None:
        self.settings = dict(settings if settings is not None else load_settings())
        self.project_root = str(Path(project_root).expanduser().resolve()) if project_root else str(self.settings.get("active_project") or "")
        self.license_secret = license_secret
        self.require_entitlement = require_entitlement
        self.command_router = command_router if command_router is not None else CommandRouter()
        self.runtime_kernel = runtime_kernel
        self.runtime_packages = tuple(runtime_packages or ())
        self.dcc = DccAPINamespace(self)
        self.call_dcc_function = DccFunctionCaller(self)
        self.reasoning = ReasoningRuntimeNamespace(self)
        self.runtime = self.reasoning
        self.features = APIFeatureNamespace(self)

    def entitlement(self) -> LicenseEntitlement:
        return verify_entitlement(self.settings, secret=self.license_secret)

    def entitlement_status(self) -> dict[str, Any]:
        return entitlement_status_row(self.settings, secret=self.license_secret)

    def _require_unlocked(self) -> LicenseEntitlement:
        entitlement = self.entitlement()
        if self.require_entitlement and not entitlement.unlocked:
            raise PermissionError(entitlement.reason or "Tech Connector license login is required.")
        if self.require_entitlement and "official_api_access" not in entitlement.capabilities:
            raise PermissionError("This license tier does not include official API access.")
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

    def capabilities(self) -> dict[str, Any]:
        return self.reasoning.capabilities()

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
            "reasoning.runtime",
            "reasoning",
            "Shared request preparation, reasoning, routing, and response runtime.",
            {
                "snapshot": self.reasoning.snapshot,
                "prepare": self.reasoning.prepare,
                "run": self.reasoning.run,
            },
            dependencies=("runtime.context", "runtime.validation"),
            lifecycle_stage="orchestration",
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


def create_api(**kwargs: Any) -> TechConnectorHeadlessAPI:
    return TechConnectorHeadlessAPI(**kwargs)


def verify_license(settings: dict[str, Any] | None = None, *, license_secret: str | None = None) -> dict[str, Any]:
    return TechConnectorHeadlessAPI(settings=settings, license_secret=license_secret, require_entitlement=False).verify_license()


def plan_prompt(prompt: str, **kwargs: Any) -> dict[str, Any]:
    return TechConnectorHeadlessAPI(**kwargs).plan_prompt(prompt)


def plan_prompt_chain(prompts: str | list[str] | tuple[str, ...], **kwargs: Any) -> dict[str, Any]:
    return TechConnectorHeadlessAPI(**kwargs).plan_prompt_chain(prompts)


def execute_action_graph(graph: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    api = TechConnectorHeadlessAPI(
        settings=kwargs.pop("settings", None),
        project_root=kwargs.pop("project_root", None),
        license_secret=kwargs.pop("license_secret", None),
        require_entitlement=kwargs.pop("require_entitlement", True),
    )
    return api.execute_action_graph(graph, **kwargs)


def execute_prompt_chain(prompts: str | list[str] | tuple[str, ...], **kwargs: Any) -> APIResult:
    api = TechConnectorHeadlessAPI(
        settings=kwargs.pop("settings", None),
        project_root=kwargs.pop("project_root", None),
        license_secret=kwargs.pop("license_secret", None),
        require_entitlement=kwargs.pop("require_entitlement", True),
        command_router=kwargs.pop("command_router", None),
    )
    return api.execute_prompt_chain(prompts, **kwargs)


def call_function(entry_point: str, *args: Any, **kwargs: Any) -> APIResult:
    api_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs.keys())
        if key in {"settings", "project_root", "license_secret", "require_entitlement"}
    }
    call_kwargs = kwargs.pop("kwargs", None)
    return TechConnectorHeadlessAPI(**api_kwargs).call_function(entry_point, *args, kwargs=call_kwargs, **kwargs)


def call_dcc_function(entry_point: str, *args: Any, **kwargs: Any) -> APIResult:
    api_kwargs = {
        key: kwargs.pop(key)
        for key in list(kwargs.keys())
        if key in {"settings", "project_root", "license_secret", "require_entitlement", "command_router"}
    }
    call_kwargs = kwargs.pop("kwargs", None)
    return TechConnectorHeadlessAPI(**api_kwargs).call_dcc_function(entry_point, *args, kwargs=call_kwargs, **kwargs)


def _reasoning_api_from_kwargs(kwargs: dict[str, Any]) -> TechConnectorHeadlessAPI:
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
        }
    }
    return TechConnectorHeadlessAPI(**api_kwargs)


def reasoning_capabilities(**kwargs: Any) -> dict[str, Any]:
    return _reasoning_api_from_kwargs(kwargs).reasoning.capabilities()


def reasoning_snapshot(prompt: str = "", **kwargs: Any) -> APIResult:
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.snapshot(prompt, context=kwargs.pop("context", None))


def prepare_reasoning_request(prompt: str, **kwargs: Any) -> APIResult:
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.prepare(prompt, context=kwargs.pop("context", None))


def run_reasoning(prompt: str, **kwargs: Any) -> APIResult:
    api = _reasoning_api_from_kwargs(kwargs)
    return api.reasoning.run(
        prompt,
        context=kwargs.pop("context", None),
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
