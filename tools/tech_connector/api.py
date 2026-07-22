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
from dataclasses import dataclass
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
from tech_connector.services.license_entitlement_service import LicenseEntitlement, entitlement_status_row, verify_entitlement
from tech_connector.services.settings_service import load_settings
from tech_connector.services.usage_provenance_service import (
    apply_python_provenance,
    build_usage_tag,
    write_project_provenance_marker,
)
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
    ) -> None:
        self.settings = dict(settings if settings is not None else load_settings())
        self.project_root = str(Path(project_root).expanduser().resolve()) if project_root else str(self.settings.get("active_project") or "")
        self.license_secret = license_secret
        self.require_entitlement = require_entitlement
        self.command_router = command_router if command_router is not None else CommandRouter()
        self.dcc = DccAPINamespace(self)
        self.call_dcc_function = DccFunctionCaller(self)

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
