from __future__ import annotations

"""Fail-closed preflight for typed cross-host pipeline action graphs."""

import importlib
import json
from typing import Any, Callable

from reasoning_runtime.action.action_graph_service import normalize_action_graph
from tech_connector.bridges.session_preferences import preferred_session_port


PIPELINE_PREFLIGHT_SCHEMA = "tech_connector.pipeline_execution_preflight.v1"
LOCAL_HOSTS = {"tech_connector"}
PYTHON_CALLABLE_HOSTS = {
    "maya", "blender", "3dsmax", "motionbuilder", "houdini",
    "substance_painter", "unreal",
}


class PipelinePreflightError(RuntimeError):
    """Raised before mutation when one or more requested hosts are not ready."""


def _typed_actions(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        action
        for action in graph.get("actions") or []
        if action.get("type") == "execute_dcc"
        and isinstance((action.get("args") or {}).get("operation_contract"), dict)
    ]


def _output_references(value: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(value, dict):
        if "from_action" in value and "result_path" in value:
            rows.append({
                "from_action": str(value.get("from_action") or ""),
                "result_path": str(value.get("result_path") or ""),
            })
        else:
            for item in value.values():
                rows.extend(_output_references(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            rows.extend(_output_references(item))
    return rows


def _pipeline_context_specs(value: Any) -> list[dict[str, Any]]:
    """Find live host inputs without treating typed output links as inputs."""
    if isinstance(value, dict):
        if value.get("$pipeline_context") in {"dcc_export_scope_v1", "dcc_input_context_v1"}:
            return [value]
        return [spec for item in value.values() for spec in _pipeline_context_specs(item)]
    if isinstance(value, (list, tuple)):
        return [spec for item in value for spec in _pipeline_context_specs(item)]
    return []


def _dependency_ancestors(action_id: str, action_by_id: dict[str, dict[str, Any]]) -> set[str]:
    ancestors: set[str] = set()
    pending = list(action_by_id.get(action_id, {}).get("depends_on") or [])
    while pending:
        dependency = str(pending.pop())
        if dependency in ancestors:
            continue
        ancestors.add(dependency)
        pending.extend(action_by_id.get(dependency, {}).get("depends_on") or [])
    return ancestors


_CONTEXT_PRODUCED_FIELDS: dict[str, set[str]] = {
    "rig_contents": {"root_joint", "joints", "armatures", "skeleton"},
    "selected_or_scene_meshes": {"mesh", "meshes"},
    "scene_contents": {"maya_scene", "blender_scene", "objects", "mesh", "meshes"},
    "current_selection": {"selection"},
    "active_object": {"active_object", "selection"},
}


def _upstream_context_producer(
    action_id: str,
    host: str,
    spec: dict[str, Any],
    action_by_id: dict[str, dict[str, Any]],
) -> str | None:
    """Find a dependent same-host stage that creates the requested live context."""

    scope = str(spec.get("scope") or "").strip().lower()
    if spec.get("$pipeline_context") == "dcc_input_context_v1":
        scope = (
            "active_object" if spec.get("context_kind") == "active_object"
            else "current_selection"
        )
    expected = _CONTEXT_PRODUCED_FIELDS.get(scope)
    if not expected:
        return None
    for ancestor_id in _dependency_ancestors(action_id, action_by_id):
        ancestor = action_by_id.get(ancestor_id) or {}
        args = dict(ancestor.get("args") or {})
        contract = dict(args.get("operation_contract") or {})
        ancestor_host = str(args.get("host") or contract.get("host") or "").lower()
        role = str(contract.get("role") or "").lower()
        produced = {str(item).lower() for item in contract.get("produces") or []}
        if (
            ancestor_host == host
            and role in {"prepare", "import", "process"}
            and produced & expected
        ):
            return ancestor_id
    return None


def _local_callable_status(callable_name: str) -> tuple[bool, str]:
    module_name, separator, attribute = str(callable_name or "").rpartition(".")
    if not separator:
        return False, "callable is not module-qualified"
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, attribute)
    except Exception as exc:
        return False, f"callable import failed: {exc}"
    if not callable(target):
        return False, "resolved object is not callable"
    return True, ""


def _session_identity(row: dict[str, Any], host: str = "") -> str:
    direct = str(row.get("session_id") or row.get("pid") or row.get("scene") or "").strip()
    if direct:
        return direct
    # Unreal's authenticated health response identifies a project, not a
    # process or scene. An explicit live port plus a valid .uproject identity
    # is enough to bind this session without accepting an anonymous socket.
    if host == "unreal":
        project_dir = str(row.get("project_dir") or "").strip().replace("\\", "/")
        project_name = str(row.get("project_name") or "").strip()
        if (project_name.lower().endswith(".uproject")
                and project_name not in {".uproject", "..uproject"}
                and "/" not in project_name and "\\" not in project_name
                and project_dir and "/" in project_dir):
            if project_dir.lower().endswith(".uproject"):
                if project_dir.rsplit("/", 1)[-1].casefold() != project_name.casefold():
                    return ""
                return project_dir
            return project_dir.rstrip("/") + "/" + project_name
    return ""


def _callable_requires_remote_probe(host: str, callable_name: str) -> bool:
    name = str(callable_name or "").strip()
    if host not in PYTHON_CALLABLE_HOSTS or not name:
        return False
    return not (
        name.startswith("ai_studio.") and ".generated." in name
        or name.startswith(("unity.command.", "photoshop.command.", "gimp.command."))
    )


def _callable_probe_source(callable_names: list[str], sys_paths: list[str]) -> str:
    return "\n".join((
        "import importlib, json, sys",
        f"_TC_CALLABLE_PATHS = {callable_names!r}",
        f"_TC_PROBE_SYS_PATHS = {sys_paths!r}",
        "for _tc_path in reversed(_TC_PROBE_SYS_PATHS):",
        "    if _tc_path and _tc_path not in sys.path:",
        "        sys.path.insert(0, _tc_path)",
        "def _tc_resolve_callable(_tc_name):",
        "    _tc_parts = _tc_name.split('.')",
        "    _tc_errors = []",
        "    for _tc_size in range(len(_tc_parts), 0, -1):",
        "        try:",
        "            _tc_value = importlib.import_module('.'.join(_tc_parts[:_tc_size]))",
        "        except Exception as _tc_exc:",
        "            _tc_errors.append(type(_tc_exc).__name__ + ': ' + str(_tc_exc))",
        "            continue",
        "        try:",
        "            for _tc_attribute in _tc_parts[_tc_size:]:",
        "                _tc_value = getattr(_tc_value, _tc_attribute)",
        "            return {'available': callable(_tc_value), 'error': '' if callable(_tc_value) else 'resolved object is not callable'}",
        "        except Exception as _tc_exc:",
        "            return {'available': False, 'error': type(_tc_exc).__name__ + ': ' + str(_tc_exc)}",
        "    return {'available': False, 'error': _tc_errors[-1] if _tc_errors else 'module could not be imported'}",
        "print(json.dumps({'schema': 'tech_connector.callable_probe.v1', 'callables': {_tc_name: _tc_resolve_callable(_tc_name) for _tc_name in _TC_CALLABLE_PATHS}}, default=str))",
    ))


def _decode_callable_probe(response: Any) -> dict[str, Any]:
    # Maya and Blender legacy execute adapters may return ``(False, stdout)``
    # when a script only prints JSON and does not set their historical result
    # sentinel. A signed local bridge response containing the exact probe
    # schema is still authoritative evidence; decode it before applying the
    # generic boolean transport convention.
    raw_payload = (
        response[1]
        if isinstance(response, tuple) and len(response) == 2
        else response
    )
    if isinstance(raw_payload, str):
        for line in reversed([value.strip() for value in raw_payload.splitlines() if value.strip()]):
            try:
                decoded_line = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                isinstance(decoded_line, dict)
                and decoded_line.get("schema") == "tech_connector.callable_probe.v1"
                and isinstance(decoded_line.get("callables"), dict)
            ):
                return {"ok": True, "error": "", "callables": dict(decoded_line["callables"])}
    try:
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import _unwrap

        payload = _unwrap(response)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "callables": {}}
    if isinstance(payload.get("callables"), dict):
        return {"ok": True, "error": "", "callables": dict(payload["callables"])}
    nested = payload.get("result")
    if isinstance(nested, str):
        for line in reversed([value.strip() for value in nested.splitlines() if value.strip()]):
            try:
                decoded = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict) and isinstance(decoded.get("callables"), dict):
                return {"ok": True, "error": "", "callables": dict(decoded["callables"])}
    return {"ok": False, "error": "Host returned no callable-probe payload.", "callables": {}}


def _probe_host_callables(
    host: str,
    callable_names: list[str],
    *,
    port: int,
    timeout_seconds: float,
    bridge_factory: Callable[[str], Any],
) -> dict[str, Any]:
    names = list(dict.fromkeys(
        name for name in callable_names if _callable_requires_remote_probe(host, name)
    ))
    if not names:
        return {"host": host, "ready": True, "status": "not_required", "callables": []}
    try:
        bridge = bridge_factory(host)
        source = _callable_probe_source(
            names,
            [str(value) for value in getattr(bridge, "SYS_PATHS", ()) if str(value)],
        )
        if host == "unreal":
            previous_port = getattr(bridge, "_forced_port", None)
            setattr(bridge, "_forced_port", int(port))
            try:
                response = bridge.execute_python(
                    source, timeout=timeout_seconds, reset_globals=True,
                )
            finally:
                setattr(bridge, "_forced_port", previous_port)
        else:
            response = bridge.execute_on_port(
                source, port=port, timeout=timeout_seconds,
            )
    except Exception as exc:
        return {
            "host": host, "ready": False, "status": "probe_failed",
            "error": str(exc), "callables": [],
        }
    decoded = _decode_callable_probe(response)
    if not decoded["ok"]:
        return {
            "host": host, "ready": False, "status": "probe_failed",
            "error": decoded["error"], "callables": [],
        }
    rows = []
    for name in names:
        value = dict(decoded["callables"].get(name) or {})
        rows.append({
            "callable": name,
            "available": bool(value.get("available")),
            "error": str(value.get("error") or ""),
        })
    return {
        "host": host,
        "ready": all(row["available"] for row in rows),
        "status": "ready" if all(row["available"] for row in rows) else "callable_unavailable",
        "error": "",
        "callables": rows,
    }


def _probe_host_session(
    host: str,
    *,
    requested_port: int | None,
    timeout_seconds: float,
    bridge_factory: Callable[[str], Any],
) -> dict[str, Any]:
    try:
        bridge = bridge_factory(host)
    except Exception as exc:
        return {
            "host": host, "ready": False, "selected_port": None,
            "status": "bridge_unavailable", "error": str(exc), "sessions": [],
        }

    candidates: list[int] = []
    source = ""
    if requested_port is not None:
        try:
            port = int(requested_port)
        except (TypeError, ValueError):
            port = 0
        if not 0 < port < 65536:
            return {
                "host": host, "ready": False, "selected_port": None,
                "status": "invalid_session_port", "error": f"Invalid port: {requested_port!r}",
                "sessions": [],
            }
        candidates = [port]
        source = "execution_policy"
    else:
        preferred = preferred_session_port(host)
        if preferred:
            candidates = [int(preferred)]
            source = "preferred_session"
        else:
            try:
                candidates = [int(port) for port in bridge.find_ports()]
            except Exception as exc:
                return {
                    "host": host, "ready": False, "selected_port": None,
                    "status": "session_discovery_failed", "error": str(exc), "sessions": [],
                }
            candidates = list(dict.fromkeys(port for port in candidates if 0 < port < 65536))
            source = "live_discovery"

    if not candidates:
        return {
            "host": host, "ready": False, "selected_port": None,
            "status": "no_live_session", "error": f"No live {host} bridge session was found.",
            "sessions": [],
        }
    if len(candidates) > 1:
        return {
            "host": host, "ready": False, "selected_port": None,
            "status": "ambiguous_live_sessions",
            "error": f"Multiple {host} sessions are live; select one before running the pipeline.",
            "candidate_ports": candidates, "sessions": [],
        }

    port = candidates[0]
    try:
        session = dict(bridge.session_info(port=port, timeout=timeout_seconds) or {})
    except Exception as exc:
        session = {"ok": False, "port": port, "error": str(exc)}
    actual_port = int(session.get("port") or 0)
    identity = _session_identity(session, host)
    ready = bool(session.get("ok")) and actual_port == port and bool(identity)
    error = ""
    if not session.get("ok"):
        error = str(session.get("error") or "Session identity readback failed.")
    elif actual_port != port:
        error = f"Requested port {port} responded as port {actual_port or 'unknown'}."
    elif not identity:
        error = "Session responded without a stable host identity."
    return {
        "host": host,
        "ready": ready,
        "selected_port": port if ready else None,
        "selection_source": source,
        "status": "ready" if ready else "identity_readback_failed",
        "error": error,
        "sessions": [session],
    }


def preflight_pipeline_execution(
    plan: dict[str, Any],
    *,
    session_ports: dict[str, int] | None = None,
    require_live_sessions: bool = False,
    timeout_seconds: float = 1.0,
    bridge_factory: Callable[[str], Any] | None = None,
    verify_host_callables: bool = True,
    verify_live_context: bool = True,
    live_context_reader: Callable[[str, dict[str, Any], int], Any] | None = None,
) -> dict[str, Any]:
    """Validate function coverage, typed handoffs, local callables, and live sessions."""
    graph = normalize_action_graph(plan)
    actions = _typed_actions(graph)
    action_ids = {str(action.get("id") or "") for action in actions}
    all_action_by_id = {
        str(action.get("id") or ""): action for action in graph.get("actions") or []
    }
    action_by_id = {str(action.get("id") or ""): action for action in actions}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    if plan.get("framework") == "dynamic_typed_pipeline_v1":
        for required in plan.get("required_inputs") or []:
            errors.append({
                "kind": "required_input",
                "stage": str(required.get("stage") or ""),
                "argument": str(required.get("argument") or ""),
                "message": str(required.get("question") or "A pipeline input is unresolved."),
            })
        for gap in plan.get("gaps") or []:
            errors.append({
                "kind": "capability_gap",
                "stage": str(gap.get("stage") or ""),
                "message": str(gap.get("message") or gap.get("reason") or "A pipeline capability is unresolved."),
                "gap_kind": str(gap.get("kind") or ""),
            })
        if plan.get("execution_ready") is False and not errors:
            errors.append({
                "kind": "not_execution_ready",
                "message": "The typed pipeline is not marked ready for execution.",
            })

    for action in actions:
        action_id = str(action.get("id") or "")
        args = dict(action.get("args") or {})
        contract = dict(args.get("operation_contract") or {})
        host = str(args.get("host") or contract.get("host") or "").strip().lower()
        operation = str(args.get("operation") or contract.get("operation") or "").strip()
        callable_name = str(args.get("callable") or contract.get("callable") or "").strip()
        row_errors: list[str] = []
        if not host:
            row_errors.append("missing host")
        if not operation:
            row_errors.append("missing operation")
        if not callable_name:
            row_errors.append("missing callable")
        if contract.get("executable") is False:
            row_errors.append("operation contract is not executable")
        if host in LOCAL_HOSTS and callable_name:
            available, reason = _local_callable_status(callable_name)
            if not available:
                row_errors.append(reason)
        dependencies = _dependency_ancestors(action_id, all_action_by_id)
        for reference in _output_references(args.get("params") or {}):
            source = reference["from_action"]
            path = reference["result_path"]
            if source not in action_ids:
                row_errors.append(f"output reference uses unknown action `{source}`")
                continue
            if source not in dependencies:
                row_errors.append(
                    f"output reference `{source}.{path}` is not in the dependency chain"
                )
            source_contract = dict(
                ((action_by_id[source].get("args") or {}).get("operation_contract") or {})
            )
            produced = set(str(item) for item in source_contract.get("produces") or [])
            root_path = path.split(".", 1)[0]
            if produced and root_path not in produced:
                row_errors.append(
                    f"output `{root_path}` is not declared by upstream action `{source}`"
                )
        for message in row_errors:
            errors.append({"kind": "action_contract", "action_id": action_id, "message": message})
        action_rows.append({
            "action_id": action_id, "host": host, "operation": operation,
            "callable": callable_name, "structurally_ready": not row_errors,
            "errors": row_errors,
        })

    requested = list(graph.get("explicit_function_requests") or [])
    unresolved = [str(item) for item in graph.get("unresolved_function_requests") or []]
    for name in unresolved:
        errors.append({
            "kind": "unresolved_requested_function", "function": name,
            "message": f"Explicitly requested function `{name}` is unresolved.",
        })
    stage_pairs = {
        (row["host"], row["operation"])
        for row in action_rows
    }
    for request in requested:
        pair = (str(request.get("host") or ""), str(request.get("operation") or ""))
        if not request.get("resolved") or pair not in stage_pairs:
            errors.append({
                "kind": "requested_function_missing_from_plan",
                "function": str(request.get("requested_name") or request.get("operation") or ""),
                "message": "An explicitly requested function is not present in executable stages.",
            })

    external_hosts = list(dict.fromkeys(
        row["host"] for row in action_rows if row["host"] and row["host"] not in LOCAL_HOSTS
    ))
    host_rows: list[dict[str, Any]] = []
    callable_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    resolved_ports: dict[str, int] = {}
    if require_live_sessions:
        if bridge_factory is None:
            from tech_connector.game_engine.integration.dcc_host_qualification_service import bridge_for_host
            bridge_factory = bridge_for_host
        configured_ports = {
            str(host).strip().lower(): int(port)
            for host, port in dict(session_ports or {}).items()
            if port not in (None, "")
        }
        for host in external_hosts:
            host_row = _probe_host_session(
                host,
                requested_port=configured_ports.get(host),
                timeout_seconds=max(0.1, min(10.0, float(timeout_seconds))),
                bridge_factory=bridge_factory,
            )
            host_rows.append(host_row)
            if host_row["ready"]:
                resolved_ports[host] = int(host_row["selected_port"])
            else:
                errors.append({
                    "kind": "host_session", "host": host,
                    "message": host_row.get("error") or host_row.get("status"),
                    "status": host_row.get("status"),
                    "candidate_ports": list(host_row.get("candidate_ports") or []),
                })
        if verify_host_callables:
            for host, port in resolved_ports.items():
                callables = [
                    row["callable"] for row in action_rows if row["host"] == host
                ]
                callable_row = _probe_host_callables(
                    host, callables, port=port,
                    timeout_seconds=max(0.1, min(30.0, float(timeout_seconds))),
                    bridge_factory=bridge_factory,
                )
                callable_rows.append(callable_row)
                if not callable_row["ready"]:
                    unavailable = [
                        row["callable"] for row in callable_row.get("callables") or []
                        if not row.get("available")
                    ]
                    errors.append({
                        "kind": "host_callable", "host": host,
                        "message": (
                            "Host callable preflight failed: " + ", ".join(unavailable)
                            if unavailable else callable_row.get("error") or callable_row.get("status")
                        ),
                        "status": callable_row.get("status"),
                        "callables": list(callable_row.get("callables") or []),
                    })
        if verify_live_context:
            from tech_connector.game_engine.integration.pipeline_operation_runtime_service import (
                _read_dcc_export_scope,
                resolve_pipeline_context_params,
            )

            context_cache: dict[tuple[str, int, str], Any] = {}
            for action in actions:
                action_id = str(action.get("id") or "")
                args = dict(action.get("args") or {})
                host = str(args.get("host") or "").strip().lower()
                params = dict(args.get("params") or {})
                specs = _pipeline_context_specs(params)
                port = resolved_ports.get(host)
                if not specs or not port:
                    continue
                upstream_producers = [
                    _upstream_context_producer(action_id, host, spec, all_action_by_id)
                    for spec in specs
                ]
                if all(upstream_producers):
                    context_rows.append({
                        "action_id": action_id,
                        "host": host,
                        "ready": True,
                        "status": "deferred_to_upstream",
                        "upstream_actions": list(dict.fromkeys(upstream_producers)),
                        "input_labels": [
                            str(spec.get("label") or spec.get("scope") or spec.get("context_kind") or "host context")
                            for spec in specs
                        ],
                    })
                    continue

                def read_context(spec: dict[str, Any]) -> Any:
                    key = (host, port, json.dumps(spec, sort_keys=True, default=str))
                    if key not in context_cache:
                        context_cache[key] = (
                            live_context_reader(host, spec, port)
                            if live_context_reader is not None
                            else _read_dcc_export_scope(
                                host, spec, session_port=port,
                                timeout_seconds=max(0.1, min(30.0, float(timeout_seconds))),
                                bridge=bridge_factory(host),
                            )
                        )
                    return context_cache[key]

                try:
                    resolved = resolve_pipeline_context_params(
                        params, host=host, session_port=port,
                        timeout_seconds=max(0.1, min(30.0, float(timeout_seconds))),
                        context_reader=read_context,
                    )
                    context_rows.append({
                        "action_id": action_id, "host": host, "ready": True,
                        "input_labels": [str(spec.get("label") or spec.get("scope") or spec.get("context_kind") or "host context") for spec in specs],
                        "resolved_counts": {
                            key: len(value) if isinstance(value, list) else 1
                            for key, value in resolved.items()
                            if _pipeline_context_specs(params.get(key))
                        },
                    })
                except Exception as exc:
                    message = f"Live {host} context is not ready: {exc}"
                    context_rows.append({
                        "action_id": action_id, "host": host, "ready": False,
                        "error": message,
                    })
                    errors.append({
                        "kind": "live_context", "action_id": action_id,
                        "host": host, "message": message,
                    })
    elif external_hosts:
        warnings.append({
            "kind": "live_sessions_not_checked",
            "hosts": external_hosts,
            "message": "Structural preflight passed without contacting external DCC sessions.",
        })

    structural_ready = not any(
        row["kind"] not in {"host_session", "host_callable", "live_context"} for row in errors
    )
    live_ready = (
        not require_live_sessions
        or all(row.get("ready") for row in host_rows)
        and len(host_rows) == len(external_hosts)
        and (
            not verify_host_callables
            or all(row.get("ready") for row in callable_rows)
        )
        and all(row.get("ready") for row in context_rows)
    )
    return {
        "schema": PIPELINE_PREFLIGHT_SCHEMA,
        "ready": structural_ready and live_ready,
        "structural_ready": structural_ready,
        "live_ready": live_ready,
        "require_live_sessions": bool(require_live_sessions),
        "typed_action_count": len(actions),
        "explicit_function_count": len(requested),
        "actions": action_rows,
        "hosts": host_rows,
        "callable_probes": callable_rows,
        "context_probes": context_rows,
        "resolved_session_ports": resolved_ports,
        "errors": errors,
        "warnings": warnings,
    }


def resolve_pipeline_session_ports(
    hosts: list[str] | tuple[str, ...],
    *,
    session_ports: dict[str, int] | None = None,
    callables_by_host: dict[str, list[str]] | None = None,
    timeout_seconds: float = 1.0,
    bridge_factory: Callable[[str], Any] | None = None,
) -> dict[str, int]:
    """Resolve and identity-check exactly one session for every external host."""
    if bridge_factory is None:
        from tech_connector.game_engine.integration.dcc_host_qualification_service import bridge_for_host
        bridge_factory = bridge_for_host
    configured = {
        str(host).strip().lower(): int(port)
        for host, port in dict(session_ports or {}).items()
        if port not in (None, "")
    }
    resolved: dict[str, int] = {}
    failures: list[str] = []
    for host in dict.fromkeys(str(item).strip().lower() for item in hosts if str(item).strip()):
        if host in LOCAL_HOSTS:
            continue
        row = _probe_host_session(
            host,
            requested_port=configured.get(host),
            timeout_seconds=max(0.1, min(10.0, float(timeout_seconds))),
            bridge_factory=bridge_factory,
        )
        if row["ready"]:
            resolved[host] = int(row["selected_port"])
            callable_row = _probe_host_callables(
                host,
                list(dict(callables_by_host or {}).get(host) or []),
                port=int(row["selected_port"]),
                timeout_seconds=max(0.1, min(30.0, float(timeout_seconds))),
                bridge_factory=bridge_factory,
            )
            if not callable_row["ready"]:
                unavailable = [
                    item["callable"] for item in callable_row.get("callables") or []
                    if not item.get("available")
                ]
                failures.append(
                    f"{host}: unavailable callables: {', '.join(unavailable)}"
                    if unavailable else
                    f"{host}: {callable_row.get('error') or callable_row.get('status')}"
                )
        else:
            failures.append(f"{host}: {row.get('error') or row.get('status')}")
    if failures:
        raise PipelinePreflightError("Pipeline host preflight failed: " + "; ".join(failures))
    return resolved


__all__ = [
    "PIPELINE_PREFLIGHT_SCHEMA", "PipelinePreflightError",
    "preflight_pipeline_execution", "resolve_pipeline_session_ports",
]
