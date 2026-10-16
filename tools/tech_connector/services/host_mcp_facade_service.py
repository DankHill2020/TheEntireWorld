"""Shared MCP-facing facade over Tech Connector's deterministic host bridges."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable

from tech_connector.bridges.host_bridge import (
    PortBoundHostBridge,
    call_python_function_via_execute,
)
from tech_connector.game_engine.integration.dcc_host_qualification_service import (
    HOST_ROLE_PROFILES,
    bridge_for_host,
)
from tech_connector.game_engine.integration.dcc_operation_service import (
    dcc_operation_registry,
)


MCP_HOSTS = (
    "maya", "unreal", "blender", "houdini", "unity", "motionbuilder",
    "3dsmax", "substance_painter", "photoshop", "gimp",
)
MUTATION_ENV = "TECH_CONNECTOR_MCP_ALLOW_MUTATION"
RAW_EXECUTION_ENV = "TECH_CONNECTOR_MCP_ALLOW_RAW_EXECUTION"


class HostMcpFacade:
    """Expose one host through stable, structured, least-authority operations."""

    def __init__(
        self,
        host: str,
        *,
        bridge: Any | None = None,
        bridge_factory: Callable[[str], Any] = bridge_for_host,
        environment: dict[str, str] | None = None,
    ) -> None:
        key = str(host or "").strip().casefold()
        if key == "max":
            key = "3dsmax"
        if key not in MCP_HOSTS:
            raise ValueError(f"Unsupported MCP host: {host}")
        self.host = key
        self.bridge = bridge if bridge is not None else bridge_factory(key)
        self.environment = environment if environment is not None else os.environ
        self.selected_port: int | None = None

    def status(self) -> dict[str, Any]:
        started = time.perf_counter()
        ports = self._find_ports()
        selected = self.selected_port if self.selected_port in ports else (ports[0] if ports else None)
        return {
            "schema": "tech_connector.host_mcp_status.v1",
            "host": self.host,
            "connected": bool(ports),
            "ports": ports,
            "selected_port": selected,
            "operation_count": len(dcc_operation_registry(self.host)),
            "mutation_enabled": self._enabled(MUTATION_ENV),
            "raw_execution_enabled": self._enabled(RAW_EXECUTION_ENV),
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }

    def sessions(self) -> dict[str, Any]:
        ports = self._find_ports()
        rows = []
        session_info = getattr(self.bridge, "session_info", None)
        for port in ports:
            if callable(session_info):
                try:
                    row = dict(session_info(port=port) or {})
                except Exception as exc:
                    row = {"ok": False, "port": port, "error": str(exc)}
            else:
                row = {"ok": True, "port": port}
            row.setdefault("port", port)
            row["selected"] = port == self.selected_port
            rows.append(row)
        return {
            "schema": "tech_connector.host_mcp_sessions.v1",
            "host": self.host,
            "selected_port": self.selected_port,
            "sessions": rows,
        }

    def select_session(self, port: int) -> dict[str, Any]:
        requested = int(port)
        ports = self._find_ports()
        if requested not in ports:
            return {
                "ok": False,
                "host": self.host,
                "requested_port": requested,
                "available_ports": ports,
                "error": "The requested host session is not currently reachable.",
            }
        self.selected_port = requested
        return {"ok": True, "host": self.host, "selected_port": requested}

    def operation_catalog(self) -> dict[str, Any]:
        operations = []
        for key, operation in sorted(dcc_operation_registry(self.host).items()):
            operations.append({
                "key": key,
                "label": str(getattr(operation, "label", key)),
                "description": str(getattr(operation, "description", "")),
                "required": list(getattr(operation, "required", ()) or ()),
                "optional": dict(getattr(operation, "optional", {}) or {}),
                "mutates_project": bool(getattr(operation, "mutates_project", False)),
                "requires_raw_execution": self._requires_raw_execution(operation),
                "execution_mode": str(getattr(operation, "execution_mode", "host_native")),
            })
        profile = HOST_ROLE_PROFILES.get(self.host)
        return {
            "schema": "tech_connector.host_mcp_operation_catalog.v1",
            "host": self.host,
            "role": str(getattr(profile, "role", "")),
            "operations": operations,
        }

    def validate_operation(self, operation_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        operation = dcc_operation_registry(self.host).get(str(operation_key or "").strip())
        values = dict(params or {})
        if operation is None:
            return {
                "ok": False,
                "host": self.host,
                "operation": operation_key,
                "errors": ["Operation is not registered for this host."],
            }
        missing = [name for name in operation.required if name not in values or values.get(name) in (None, "")]
        known = set(operation.required) | set(operation.optional)
        unknown = sorted(set(values) - known)
        errors = [f"Missing required parameter: {name}" for name in missing]
        return {
            "ok": not errors,
            "host": self.host,
            "operation": operation.key,
            "mutates_project": bool(operation.mutates_project),
            "requires_raw_execution": self._requires_raw_execution(operation),
            "errors": errors,
            "warnings": [f"Unrecognized parameter will be forwarded: {name}" for name in unknown],
            "resolved_params": {**dict(operation.optional), **values},
        }

    def run_operation(
        self,
        operation_key: str,
        params: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        validation = self.validate_operation(operation_key, params)
        if not validation.get("ok"):
            return validation
        operation = dcc_operation_registry(self.host)[str(operation_key).strip()]
        if operation.mutates_project and not (approved and self._enabled(MUTATION_ENV)):
            return {
                "ok": False,
                "status": "approval_required",
                "host": self.host,
                "operation": operation.key,
                "mutates_project": True,
                "required_controls": ["approved=true", f"{MUTATION_ENV}=1"],
                "error": "MCP mutation is disabled until both user approval and installation policy allow it.",
            }
        if self._requires_raw_execution(operation) and not self._enabled(RAW_EXECUTION_ENV):
            return {
                "ok": False,
                "status": "approval_required",
                "host": self.host,
                "operation": operation.key,
                "mutates_project": bool(operation.mutates_project),
                "requires_raw_execution": True,
                "required_controls": ["approved=true", f"{MUTATION_ENV}=1", f"{RAW_EXECUTION_ENV}=1"],
                "error": "This registered operation can execute arbitrary host code and raw execution is disabled.",
            }
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        try:
            ok, payload = self._execute_operation(operation, validation["resolved_params"], float(timeout))
            error = "" if ok else str(payload)
        except Exception as exc:
            ok, payload, error = False, None, str(exc)
        return {
            "schema": "tech_connector.host_mcp_operation_receipt.v1",
            "request_id": request_id,
            "ok": bool(ok),
            "status": "completed" if ok else "failed",
            "host": self.host,
            "session_port": self._target_port(),
            "operation": operation.key,
            "mutates_project": bool(operation.mutates_project),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "result": self._decode(payload) if ok else None,
            "error": error,
        }

    def execute_python(self, code: str, *, approved: bool = False, timeout: float = 30.0) -> dict[str, Any]:
        if not (approved and self._enabled(MUTATION_ENV) and self._enabled(RAW_EXECUTION_ENV)):
            return {
                "ok": False,
                "status": "approval_required",
                "host": self.host,
                "required_controls": ["approved=true", f"{MUTATION_ENV}=1", f"{RAW_EXECUTION_ENV}=1"],
                "error": "Raw host execution is disabled. Prefer a registered typed operation.",
            }
        bridge_info = getattr(self.bridge, "info", None)
        if bridge_info is not None and not bool(getattr(bridge_info, "supports_direct_execute", False)):
            return {
                "ok": False,
                "status": "unsupported",
                "host": self.host,
                "error": "This bridge exposes typed commands but does not support raw host execution.",
            }
        bridge = self._bound_bridge()
        execute = getattr(bridge, "execute", None) if self.selected_port is not None else (
            getattr(bridge, "execute_python", None) or getattr(bridge, "execute", None)
        )
        if not callable(execute):
            return {"ok": False, "status": "unsupported", "host": self.host, "error": "Bridge has no raw execution endpoint."}
        try:
            response = execute(str(code), timeout=float(timeout))
            ok, payload = self._normalize_response(response)
            return {"ok": ok, "host": self.host, "session_port": self._target_port(), "result": self._decode(payload) if ok else None, "error": "" if ok else str(payload)}
        except Exception as exc:
            return {"ok": False, "host": self.host, "error": str(exc)}

    def _execute_operation(self, operation: Any, params: dict[str, Any], timeout: float) -> tuple[bool, Any]:
        if str(getattr(operation, "execution_mode", "host_native")) == "user_delegated":
            return False, "Operation is intentionally user-delegated and cannot run through MCP."
        if self.host == "maya" and str(operation.function).startswith("ai_studio.maya.generated."):
            from tech_connector.game_engine.integration.dcc_operation_service import maya_operation_code

            code = maya_operation_code(operation.key, params)
            return self._normalize_response(self._bound_bridge().execute(code, timeout=timeout))
        if self.host == "blender" and str(operation.function).startswith("ai_studio.blender.generated."):
            from tech_connector.game_engine.integration.dcc_operation_service import blender_operation_code

            code = blender_operation_code(operation.key, params)
            return self._normalize_response(self._bound_bridge().execute(code, timeout=timeout))
        if self.host == "unity":
            command = str(operation.function).removeprefix("unity.command.")
            return self._normalize_response(self.bridge.execute_command(command, params, port=self._target_port(), timeout=timeout))
        if self.host == "gimp":
            command = str(operation.function).removeprefix("gimp.command.")
            return self._normalize_response(self.bridge.execute_command(command, params, port=self._target_port()))
        if self.host == "photoshop":
            command = str(operation.function).removeprefix("photoshop.command.")
            if command == "document.batch_play":
                command = "batch_play"
            if self.selected_port is not None:
                payload = json.dumps({"command": command, "params": params})
                return self._normalize_response(
                    self.bridge.execute_on_port(payload, port=self.selected_port, timeout=timeout)
                )
            return self._normalize_response(self.bridge.execute_command(command, params))
        if self.host == "unreal":
            bridge = self.bridge
            if self.selected_port is not None:
                from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
                bridge = UnrealBridge(forced_port=self.selected_port)
            safe_call = getattr(bridge, "safe_call", None)
            if callable(safe_call):
                return self._normalize_response(safe_call(operation.function, kwargs=params, timeout=timeout, label="mcp"))
        bridge = self._bound_bridge()
        return self._normalize_response(
            call_python_function_via_execute(
                bridge,
                operation.function,
                kwargs=params,
                sys_paths=getattr(self.bridge, "SYS_PATHS", ()),
                timeout=timeout,
            )
        )

    def _bound_bridge(self) -> Any:
        return PortBoundHostBridge(self.bridge, self.selected_port) if self.selected_port is not None else self.bridge

    def _find_ports(self) -> list[int]:
        finder = getattr(self.bridge, "find_ports", None)
        if callable(finder):
            try:
                return [int(value) for value in finder()]
            except Exception:
                return []
        single = getattr(self.bridge, "find_port", lambda: None)()
        return [int(single)] if single else []

    def _target_port(self) -> int | None:
        if self.selected_port is not None:
            return self.selected_port
        ports = self._find_ports()
        return ports[0] if ports else None

    def _enabled(self, name: str) -> bool:
        return str(self.environment.get(name, "")).strip().casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _requires_raw_execution(operation: Any) -> bool:
        key = str(getattr(operation, "key", "")).casefold()
        return key.endswith("script.run") or key.endswith("api.call")

    @staticmethod
    def _normalize_response(response: Any) -> tuple[bool, Any]:
        if isinstance(response, tuple) and len(response) == 2:
            return bool(response[0]), response[1]
        if isinstance(response, dict) and "ok" in response:
            return bool(response.get("ok")), response.get("result", response)
        return True, response

    @staticmethod
    def _decode(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return text


def facade_contract(host: str) -> dict[str, Any]:
    """Return a non-live MCP contract for setup and unit qualification."""
    key = "3dsmax" if str(host).casefold() == "max" else str(host).casefold()
    operations = dcc_operation_registry(key)
    return {
        "schema": "tech_connector.host_mcp_contract.v1",
        "host": key,
        "supported": key in MCP_HOSTS,
        "operation_count": len(operations),
        "read_tools": ("status", "sessions", "operation_catalog", "validate_operation"),
        "controlled_tools": ("select_session", "run_operation", "execute_python"),
        "mutation_policy_environment": MUTATION_ENV,
        "raw_execution_policy_environment": RAW_EXECUTION_ENV,
    }
