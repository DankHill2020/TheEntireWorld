from __future__ import annotations

"""Direct Unreal HTTP bridge.

Provides a small but robust HTTP client for the Unreal bridge with:
- request IDs for tracing
- structured response envelopes
- lightweight retry handling for transient failures
- operation logging for UI/debug visibility
"""

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from tech_connector.bridges.session_discovery import candidate_session_ports, discover_open_ports
from tech_connector.bridges.session_authorization import bridge_session_token
from tech_connector.dcc_intelligence.runtime import TTLMemoryCache, elapsed_ms, iso_now
from tech_connector.models.constants import APP_DIR, TOOLS_ROOT
from tech_connector.services.jsonl_retention_service import append_jsonl_record
from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


LOGGER = logging.getLogger(__name__)


class UnrealBridge(DCCBridgeDelegateMixin):
    """Deterministic Unreal communication via HTTP bridge."""

    def __init__(self, forced_port: int | None = None):
        self.init_delegate("unreal")
        self._forced_port = int(forced_port) if forced_port else None

    PORT_FILES = [
        str(APP_DIR / "unreal_http_port.txt"),
        str(TOOLS_ROOT / "unreal_http_port.txt"),
    ]
    DEFAULT_PORT = 12347
    HOST = "127.0.0.1"
    DEFAULT_TIMEOUT = 5.0
    DEFAULT_RETRY_DELAY = 0.2
    LOG_FILE = APP_DIR / "unreal_request_log.jsonl"
    MAX_LOG_BYTES = 16 * 1024 * 1024
    MAX_LOG_ARCHIVES = 3
    _health_cache = TTLMemoryCache()
    _request_cache = TTLMemoryCache()

    def _candidate_ports(self) -> list[int]:
        if self._forced_port:
            return [self._forced_port]
        return candidate_session_ports(
            "unreal",
            port_files=self.PORT_FILES,
            environment_variable="UNREAL_HTTP_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="UNREAL_HTTP_PORT_SCAN_COUNT",
        )

    def find_ports(self, host=HOST) -> list[int]:
        return discover_open_ports(self._candidate_ports(), host=host)

    def find_port(self, host=HOST):
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def _parse_raw(self, raw: str) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            return raw

    @staticmethod
    def _payload_size_bytes(payload: bytes | None) -> int:
        return len(payload or b"")

    @staticmethod
    def _response_size_bytes(raw: str) -> int:
        return len((raw or "").encode("utf-8", errors="replace"))

    @staticmethod
    def _is_transient_error(error_text: str) -> bool:
        text = (error_text or "").lower()
        transient_markers = (
            "timed out",
            "connection refused",
            "connection reset",
            "connection aborted",
            "temporarily unavailable",
            "remote end closed connection",
            "failed to establish a new connection",
            "unreachable",
        )
        return any(marker in text for marker in transient_markers)

    @staticmethod
    def _is_safe_retry(function_path: str, label: str = "") -> bool:
        text = f"{function_path} {label}".lower()
        destructive_markers = (
            "delete",
            "destroy",
            "rename",
            "move",
            "save",
            "import",
            "export",
            "set_",
            "create",
            "spawn",
            "write",
            "apply",
            "compile",
            "exec",
            "run_python",
            "prototype",
            "mutation",
        )
        return not any(marker in text for marker in destructive_markers)

    def _log_request(self, entry: dict[str, Any]) -> None:
        try:
            log_path = Path(self.LOG_FILE)
            append_jsonl_record(
                log_path,
                entry,
                max_bytes=self.MAX_LOG_BYTES,
                archive_count=self.MAX_LOG_ARCHIVES,
            )
        except (OSError, TypeError, ValueError) as exc:
            LOGGER.warning("Could not write Unreal request log %s: %s", self.LOG_FILE, exc)
        self._request_cache.set("last_request", dict(entry))

    def get_last_request_status(self) -> dict[str, Any] | None:
        cached = self._request_cache.get("last_request", 3600.0)
        return dict(cached) if isinstance(cached, dict) else None

    def _envelope(
        self,
        *,
        ok: bool,
        request_id: str,
        operation: str,
        data: Any = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        duration_ms: float = 0.0,
        response_size: int = 0,
        endpoint: str = "",
        timeout: float | None = None,
        attempts: int = 1,
        payload_size: int = 0,
        status_code: int | None = None,
        raw: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        return {
            "ok": bool(ok),
            "request_id": request_id,
            "operation": operation,
            "label": label,
            "data": data if data is not None else {},
            "result": data,
            "errors": errors or [],
            "warnings": warnings or [],
            "error": (errors or [None])[0],
            "duration_ms": duration_ms,
            "response_size": response_size,
            "endpoint": endpoint,
            "timeout": timeout,
            "attempts": attempts,
            "payload_size": payload_size,
            "status_code": status_code,
            "raw": raw,
        }

    def safe_call(
        self,
        function_path: str,
        args=None,
        kwargs=None,
        timeout: float = 5.0,
        retries: int = 1,
        label: str = "",
        retry_safe: bool | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        args = args or []
        kwargs = kwargs or {}
        timeout = float(timeout or self.DEFAULT_TIMEOUT)
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        last_raw = ""
        last_error = None
        parsed: Any = None
        status_code = None
        port = self.find_port(self.HOST)
        endpoint = f"http://{self.HOST}:{port or self.DEFAULT_PORT}"
        payload = json.dumps(
            {
                "function": function_path,
                "args": args,
                "kwargs": kwargs,
                "request_id": request_id,
                "operation": operation or label or function_path,
                "bridge_session": bridge_session_token("unreal"),
            }
        ).encode("utf-8")
        payload_size = self._payload_size_bytes(payload)
        attempts = max(1, int(retries) + 1)
        if retry_safe is None:
            retry_safe = self._is_safe_retry(function_path, label)
        if not retry_safe:
            attempts = 1

        if not port:
            entry = self._envelope(
                ok=False,
                request_id=request_id,
                operation=operation or function_path,
                data={},
                errors=[
                    f"Unreal HTTP bridge not found on port {self.DEFAULT_PORT}. Start your Unreal HTTP server first."
                ],
                duration_ms=elapsed_ms(started),
                response_size=0,
                endpoint=endpoint,
                timeout=timeout,
                attempts=0,
                payload_size=payload_size,
                raw="",
                label=label,
            )
            self._log_request(
                {
                    **entry,
                    "target_port": port,
                    "started_at": iso_now(),
                    "finished_at": iso_now(),
                    "success": False,
                    "returned_error_text": entry["error"],
                }
            )
            return entry

        started_at = iso_now()
        for attempt in range(1, attempts + 1):
            attempt_started = time.monotonic()
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-AI-Studio-Request-ID": request_id,
                        "X-AI-Studio-Operation": operation or label or function_path,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    status_code = getattr(response, "status", None)
                    last_raw = response.read().decode("utf-8", errors="replace")
                parsed = self._parse_raw(last_raw)
                if isinstance(parsed, dict) and parsed.get("error"):
                    last_error = str(parsed.get("error"))
                    if (
                        attempt < attempts
                        and retry_safe
                        and self._is_transient_error(last_error)
                    ):
                        time.sleep(self.DEFAULT_RETRY_DELAY)
                        continue
                    break
                entry = self._envelope(
                    ok=True,
                    request_id=request_id,
                    operation=operation or function_path,
                    data=parsed,
                    warnings=list(parsed.get("warnings") or [])
                    if isinstance(parsed, dict)
                    else [],
                    duration_ms=elapsed_ms(started),
                    response_size=self._response_size_bytes(last_raw),
                    endpoint=endpoint,
                    timeout=timeout,
                    attempts=attempt,
                    payload_size=payload_size,
                    status_code=status_code,
                    raw=last_raw,
                    label=label,
                )
                self._log_request(
                    {
                        **entry,
                        "target_port": port,
                        "started_at": started_at,
                        "finished_at": iso_now(),
                        "attempt_duration_ms": elapsed_ms(attempt_started),
                        "success": True,
                        "returned_error_text": "",
                    }
                )
                return entry
            except TimeoutError:
                last_error = f"Timed out after {timeout}s"
            except socket.timeout:
                last_error = f"Timed out after {timeout}s"
            except urllib.error.HTTPError as exc:
                status_code = getattr(exc, "code", None)
                try:
                    last_raw = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    last_raw = ""
                parsed = self._parse_raw(last_raw) if last_raw else None
                last_error = f"Unreal bridge HTTP {status_code}: {parsed.get('error') if isinstance(parsed, dict) and parsed.get('error') else last_raw or exc.reason}"
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                last_error = f"Unreal bridge request failed: {reason}"
            except Exception as exc:
                last_error = str(exc)

            if (
                attempt < attempts
                and retry_safe
                and self._is_transient_error(last_error or "")
            ):
                time.sleep(self.DEFAULT_RETRY_DELAY)
                continue
            break

        entry = self._envelope(
            ok=False,
            request_id=request_id,
            operation=operation or function_path,
            data=parsed
            if parsed is not None
            else (self._parse_raw(last_raw) if last_raw else {}),
            errors=[last_error or "Unreal bridge call failed."],
            duration_ms=elapsed_ms(started),
            response_size=self._response_size_bytes(last_raw),
            endpoint=endpoint,
            timeout=timeout,
            attempts=min(attempts, attempt if "attempt" in locals() else attempts),
            payload_size=payload_size,
            status_code=status_code,
            raw=last_raw,
            label=label,
        )
        self._log_request(
            {
                **entry,
                "target_port": port,
                "started_at": started_at,
                "finished_at": iso_now(),
                "success": False,
                "returned_error_text": entry["error"],
            }
        )
        return entry


    def _unreal_python_bootstrap_paths(self) -> list[str]:
        """Return Tech Connector paths that Unreal's Python interpreter should see.

        Unreal executes dynamic commands from its own Python process. The app can
        import Tech Connector modules normally, but Unreal may only know about the
        shared tools root. Add the tools root for package imports plus the app
        and bridge directories for the existing direct-import entry points:

            from tech_connector.bridges.unreal import unreal_dynamic_exec
            import unreal_dynamic_exec
        """
        try:
            bridge_dir = Path(__file__).resolve().parent
            app_root = bridge_dir.parents[1]
            tools_root = next(
                candidate
                for candidate in (app_root, *app_root.parents)
                if candidate.name.lower() == "tools"
            )
            candidates = [
                tools_root,
                app_root,
                app_root / "bridges",
                bridge_dir,
            ]
        except Exception:
            candidates = []
        out: list[str] = []
        for path in candidates:
            try:
                text = str(Path(path).resolve())
            except Exception:
                text = str(path)
            if text and text not in out:
                out.append(text)
        return out

    def _build_unreal_python_bootstrap_source(self) -> str:
        paths = self._unreal_python_bootstrap_paths()
        return f"""
import json
import os
import sys

_ai_studio_paths = {paths!r}
_added = []
for _path in _ai_studio_paths:
    try:
        _norm = os.path.normpath(str(_path))
        if _norm and _norm not in sys.path:
            sys.path.insert(0, _norm)
            _added.append(_norm)
    except Exception:
        pass

_imports = {{}}
try:
    from tech_connector.bridges.unreal import unreal_dynamic_exec as _qualified_dynamic_exec
    _imports['qualified_unreal_dynamic_exec'] = getattr(_qualified_dynamic_exec, '__file__', '')
except Exception as _exc:
    _imports['qualified_unreal_dynamic_exec_error'] = str(_exc)

try:
    import unreal_dynamic_exec as _direct_dynamic_exec
    _imports['direct_unreal_dynamic_exec'] = getattr(_direct_dynamic_exec, '__file__', '')
except Exception as _exc:
    _imports['direct_unreal_dynamic_exec_error'] = str(_exc)

try:
    import unreal_tools as _unreal_tools
    _imports['unreal_tools'] = getattr(_unreal_tools, '__file__', '')
except Exception as _exc:
    _imports['unreal_tools_error'] = str(_exc)

result = {{
    'ok': bool(_imports.get('qualified_unreal_dynamic_exec') or _imports.get('direct_unreal_dynamic_exec')),
    'added_paths': _added,
    'paths': _ai_studio_paths,
    'imports': _imports,
}}
print(json.dumps(result))
"""

    def bootstrap_unreal_python_paths(self, timeout: float = 3.0, force: bool = False) -> dict[str, Any]:
        """Add Tech Connector paths to Unreal's sys.path and verify helper imports.

        Prefer the packaged dynamic executor. The legacy eval endpoint is only a
        bootstrap fallback for installs where the helper is not yet importable.
        """
        cache_key = "unreal_python_bootstrap"
        if not force:
            cached = self._request_cache.get(cache_key, 300.0)
            if isinstance(cached, dict) and cached.get("ok"):
                return dict(cached)
        source = self._build_unreal_python_bootstrap_source()
        normalized = {}
        for function_path in (
            "tech_connector.bridges.unreal.unreal_dynamic_exec.run_python",
            "unreal_dynamic_exec.run_python",
        ):
            result = self.safe_call(
                function_path,
                args=[source],
                kwargs={"reset_globals": False},
                timeout=timeout,
                retries=0,
                retry_safe=False,
                label="python_path_bootstrap",
                operation="bootstrap_unreal_python_paths",
            )
            normalized = self._normalize_execute_python_response(result)
            if normalized.get("ok"):
                break
            if not self._looks_like_missing_dynamic_exec(normalized):
                break
        if not normalized.get("ok") and self._looks_like_missing_dynamic_exec(normalized):
            result = self.safe_call(
                "eval",
                args=[source],
                kwargs={},
                timeout=timeout,
                retries=0,
                retry_safe=False,
                label="python_path_bootstrap_legacy_eval",
                operation="bootstrap_unreal_python_paths",
            )
            normalized = self._normalize_execute_python_response(
                result,
                fallback_used=True,
                fallback_name="legacy_eval_bootstrap",
            )
        data = normalized.get("data")
        if isinstance(data, str):
            parsed = self._parse_raw(data)
            if isinstance(parsed, dict):
                normalized["data"] = parsed
                normalized["result"] = parsed
        self._request_cache.set(cache_key, dict(normalized))
        return normalized

    @staticmethod
    def _looks_like_missing_dynamic_exec(response: dict[str, Any]) -> bool:
        """Return True when Unreal cannot import the helper module.

        Some Unreal installs can call packaged `unreal_tools.*` functions but do
        not have Tech Connector's `unreal_dynamic_exec.py` on Unreal's Python path.
        In that case, fall back to the bridge server's legacy `eval` endpoint.
        """
        haystack = " ".join(
            str(response.get(key) or "")
            for key in ("error", "raw", "data", "result")
        ).lower()
        return (
            "unreal_dynamic_exec" in haystack
            and (
                "no module named" in haystack
                or "modulenotfounderror" in haystack
                or "import" in haystack
            )
        )

    def _normalize_execute_python_response(
        self,
        response: dict[str, Any],
        *,
        fallback_used: bool = False,
        fallback_name: str = "",
    ) -> dict[str, Any]:
        """Normalize bridge envelopes into a dynamic-python-like envelope.

        Callers currently expect the top-level safe-call envelope, but the
        payload may be either:
        - the `unreal_dynamic_exec.run_python` dict,
        - a JSON string printed/returned by the legacy eval endpoint,
        - or an arbitrary eval result string.
        """
        out = dict(response)
        warnings = list(out.get("warnings") or [])
        if fallback_used:
            warnings.append(f"Dynamic Python fallback used: {fallback_name}")
        data = out.get("data")

        # Newer Unreal helper functions may return the legacy bridge-compatible
        # tuple/list shape: (ok, payload). JSON turns that into [ok, payload].
        if isinstance(data, (list, tuple)) and len(data) == 2 and isinstance(data[0], bool):
            python_ok, payload = data
            out["python_ok"] = bool(python_ok)
            out["data"] = payload
            out["result"] = payload
            data = payload
            if not python_ok:
                out["ok"] = False
                out["error"] = out.get("error") or str(payload)
                out["errors"] = [out["error"]]

        if isinstance(data, str):
            parsed = self._parse_raw(data)
            if isinstance(parsed, dict):
                data = parsed
                out["data"] = parsed
                out["result"] = parsed
        if isinstance(data, dict):
            # If the payload itself is the dynamic runner result, preserve its
            # metadata but expose the useful JSON stdout/result as `data`.
            if "ok" in data and any(k in data for k in ("stdout", "stderr", "traceback")):
                runner = data
                out["python_runner"] = runner
                out["python_ok"] = bool(runner.get("ok"))
                out["python_result"] = runner.get("result")
                out["python_stdout"] = runner.get("stdout")
                out["python_stderr"] = runner.get("stderr")

                parsed_payload = None
                for line in reversed(str(runner.get("stdout") or "").splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed_payload = json.loads(line)
                        break
                    except Exception:
                        pass
                if parsed_payload is None:
                    parsed_payload = self._parse_raw(runner.get("result"))

                if parsed_payload is not None:
                    out["data"] = parsed_payload
                    out["result"] = parsed_payload

                if runner.get("error") and not out.get("error"):
                    out["error"] = str(runner.get("error"))
                    out["errors"] = [str(runner.get("error"))]
                    out["ok"] = False
        out["warnings"] = warnings
        return out

    def _execute_python_via_eval(
        self, source: str, timeout: float = 30.0, reset_globals: bool = False
    ) -> dict[str, Any]:
        """Fallback for older Unreal HTTP bridge servers.

        The older adapter in this project used `function='eval'` for arbitrary
        code execution. Keep that path alive so live editor context still works
        even when `unreal_dynamic_exec.py` has not been installed into Unreal's
        Python path yet.
        """
        if reset_globals:
            # The eval endpoint generally executes in the bridge's normal Python
            # context and may not support a reset flag. Keep the request explicit
            # rather than pretending state was reset.
            source = "# Tech Connector requested reset_globals; legacy eval endpoint may ignore this.\n" + (source or "")
        return self.safe_call(
            "eval",
            args=[source],
            kwargs={},
            timeout=timeout,
            retries=0,
            retry_safe=False,
            label="dynamic_python_eval_fallback",
            operation="execute_python",
        )

    def execute_python(
        self, source: str, timeout: float = 30.0, reset_globals: bool = False
    ) -> dict[str, Any]:
        bootstrap = self.bootstrap_unreal_python_paths(timeout=min(float(timeout or 3.0), 3.0))

        candidates = [
            "tech_connector.bridges.unreal.unreal_dynamic_exec.run_python",
            "unreal_dynamic_exec.run_python",
        ]
        failures: list[dict[str, Any]] = []
        for function_path in candidates:
            response = self.safe_call(
                function_path,
                args=[source],
                kwargs={"reset_globals": reset_globals},
                timeout=timeout,
                retries=0,
                retry_safe=False,
                label="dynamic_python",
                operation="execute_python",
            )
            normalized = self._normalize_execute_python_response(response)
            normalized["bootstrap"] = {
                "ok": bool(bootstrap.get("ok")),
                "data": bootstrap.get("data"),
                "error": bootstrap.get("error"),
            }
            normalized["dynamic_exec_function"] = function_path
            if normalized.get("ok") or not self._looks_like_missing_dynamic_exec(normalized):
                return normalized
            failures.append({
                "function": function_path,
                "error": normalized.get("error"),
                "raw": normalized.get("raw"),
            })

        fallback = self._execute_python_via_eval(
            self._build_unreal_python_bootstrap_source() + "\n" + (source or ""),
            timeout=timeout,
            reset_globals=reset_globals,
        )
        normalized = self._normalize_execute_python_response(
            fallback,
            fallback_used=True,
            fallback_name="eval_after_python_path_bootstrap",
        )
        normalized["bootstrap"] = {
            "ok": bool(bootstrap.get("ok")),
            "data": bootstrap.get("data"),
            "error": bootstrap.get("error"),
        }
        normalized["fallback_from"] = failures
        return normalized

    def export_animation_assets(
        self, asset_paths: list[str] | tuple[str, ...], *, timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Reflect selected Unreal animation assets into converter-ready JSON."""
        paths = [str(value) for value in asset_paths]
        script = (
            "import json\n"
            "from unreal_tools.animation_interchange_exporter import export_animation_assets\n"
            f"print(json.dumps(export_animation_assets({paths!r})))\n"
        )
        response = self.execute_python(script, timeout=timeout, reset_globals=True)
        data = response.get("data")
        if response.get("ok") and isinstance(data, dict):
            return {"ok": True, "data": data, "warnings": list(response.get("warnings") or [])}
        return {"ok": False, "error": str(response.get("error") or "Unreal returned invalid animation export data."), "raw": response}

    def get_scene_snapshot_code(
        self,
        *,
        selected_only: bool = False,
        include_materials: bool = True,
        limit: int = 500,
        **_kwargs,
    ) -> str:
        from tech_connector.game_engine.integration.scene_snapshot_provider import unreal_scene_snapshot_code

        return unreal_scene_snapshot_code(
            selected_only=selected_only,
            include_materials=include_materials,
            limit=limit,
        )

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        include_materials: bool = True,
        limit: int = 500,
        timeout: float = 30.0,
        **_kwargs,
    ) -> tuple:
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        requested_port = _kwargs.get("port")
        target = self
        if requested_port is not None and self._forced_port != int(requested_port):
            target = type(self)(forced_port=int(requested_port))
        response = target.execute_python(
            self.get_scene_snapshot_code(
                selected_only=selected_only,
                include_materials=include_materials,
                limit=limit,
            ),
            timeout=timeout,
            reset_globals=True,
        )
        if not response.get("ok"):
            return False, response.get("error") or response.get("raw") or str(response)
        raw = response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or ""
        if isinstance(raw, dict):
            raw = raw.get("stdout") or raw.get("output") or raw.get("result") or json.dumps(raw)
        return parse_scene_snapshot_output(str(raw).strip(), "unreal")

    def execute_context_call(
        self,
        call_name: str,
        *,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a shared DCC context registry call through this Unreal bridge."""
        try:
            from tech_connector.game_engine.integration.context_call_registry import execute_context_call
        except Exception:
            try:
                from context_call_registry import execute_context_call
            except Exception as exc:
                return {"ok": False, "data": {}, "error": str(exc)}
        return execute_context_call(
            "unreal",
            call_name,
            self,
            args=args or [],
            kwargs=kwargs or {},
            timeout=timeout,
        )

    def inspect_blueprint_graph(
        self, asset_path: str, timeout: float = 10.0
    ) -> dict[str, Any]:
        script = f"""
import json, unreal
asset_path = {asset_path!r}
out = {{'asset_path': asset_path, 'graphs': [], 'errors': [], 'warnings': []}}
try:
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not bp:
        out['errors'].append('Asset could not be loaded')
    else:
        try:
            subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            if subsystem:
                subsystem.open_editor_for_assets([bp])
        except Exception as open_exc:
            out['warnings'].append('Open editor before graph inspect failed: ' + str(open_exc))
        try:
            graphs = unreal.BlueprintEditorLibrary.list_graphs(bp)
            for graph in graphs or []:
                graph_data = {{'name': str(graph.get_name()), 'nodes': []}}
                graph_editor = None
                try:
                    graph_editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(bp, str(graph.get_name()))
                except Exception as editor_exc:
                    graph_data['editor_error'] = str(editor_exc)
                try:
                    nodes = unreal.BlueprintGraphEditor.list_all_nodes(graph_editor) if graph_editor else []
                    for node in nodes or []:
                        pins = []
                        properties = []
                        try:
                            for pin in getattr(node, 'pins', []) or []:
                                links = []
                                try:
                                    for linked in pin.linked_to or []:
                                        owner = linked.get_owning_node()
                                        links.append({{'node': str(owner.get_name()) if owner else '', 'pin': str(linked.get_name())}})
                                except Exception:
                                    pass
                                pins.append({{'name': str(pin.get_name()), 'direction': str(pin.direction), 'linked_to': links}})
                        except Exception:
                            pass
                        try:
                            for prop_name in ('node_comment', 'enabled_state', 'error_msg'):
                                try:
                                    properties.append({{'name': prop_name, 'value': str(node.get_editor_property(prop_name))}})
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            title = str(unreal.BlueprintEditorLibrary.get_node_title(node))
                        except Exception:
                            title = str(node.get_name())
                        try:
                            position = str(unreal.BlueprintEditorLibrary.get_node_pos(node))
                        except Exception:
                            position = ''
                        graph_data['nodes'].append({{'name': str(node.get_name()), 'title': title, 'class': str(node.get_class().get_name()), 'pins': pins, 'properties': properties, 'position': position}})
                except Exception as graph_exc:
                    graph_data['error'] = str(graph_exc)
                out['graphs'].append(graph_data)
        except Exception as exc:
            out['errors'].append(str(exc))
except Exception as exc:
    out['errors'].append(str(exc))
print(json.dumps(out))
"""
        return self.execute_python(script, timeout=timeout, reset_globals=True)

    def focus_blueprint_graph_item(
        self,
        blueprint_path: str,
        graph_name: str,
        node_name: str = "",
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        script = f"""
import json, unreal
blueprint_path = {blueprint_path!r}
graph_name = {graph_name!r}
node_name = {node_name!r}
out = {{
    'ok': False,
    'blueprint_path': blueprint_path,
    'graph_name': graph_name,
    'node_name': node_name,
    'asset_opened': False,
    'graph_opened': False,
    'node_found': False,
    'node_focused': False,
    'focus_method': '',
    'focused_node': '',
    'available_nodes': [],
    'warnings': [],
    'errors': [],
}}
try:
    bp = unreal.EditorAssetLibrary.load_asset(blueprint_path)
    if not bp:
        out['errors'].append('Blueprint asset could not be loaded')
    else:
        try:
            subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            if subsystem:
                out['asset_opened'] = bool(subsystem.open_editor_for_assets([bp]))
        except Exception as open_exc:
            out['warnings'].append('Asset editor open failed: ' + str(open_exc))
        graph_editor = None
        try:
            graph_editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(bp, graph_name)
            out['graph_opened'] = bool(graph_editor)
        except Exception as graph_exc:
            out['errors'].append('Graph editor open failed: ' + str(graph_exc))
        if graph_editor:
            nodes = []
            try:
                nodes = unreal.BlueprintGraphEditor.list_all_nodes(graph_editor) or []
            except Exception as nodes_exc:
                out['warnings'].append('Node list failed: ' + str(nodes_exc))
            target = None
            for node in nodes:
                name = str(node.get_name())
                try:
                    title = str(unreal.BlueprintEditorLibrary.get_node_title(node))
                except Exception:
                    title = ''
                out['available_nodes'].append({{'name': name, 'title': title, 'class': str(node.get_class().get_name())}})
                if node_name and (name == node_name or title == node_name):
                    target = node
            if target:
                out['node_found'] = True
                out['focused_node'] = str(target.get_name())
                out['node_focused'] = True
                out['focus_method'] = 'opened_graph_and_resolved_node_position'
                try:
                    out['node_position'] = str(unreal.BlueprintEditorLibrary.get_node_pos(target))
                except Exception:
                    pass
                out['warnings'].append('Blueprint graph node visual selection is not exposed by this Unreal Python API; opened graph and resolved node position instead.')
            elif node_name:
                out['warnings'].append('Requested node not found in open graph: ' + node_name)
        out['ok'] = bool(out['asset_opened'] and out['graph_opened']) and not out['errors']
except Exception as exc:
    out['errors'].append(str(exc))
print(json.dumps(out))
"""
        return self.execute_python(script, timeout=timeout, reset_globals=True)

    def backup_blueprint_asset(
        self,
        asset_path: str,
        backup_root: str = "/Game/AIStudio/GraphPatchBackups",
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        script = f"""
import json, unreal, uuid
asset_path = {asset_path!r}
backup_root = {backup_root!r}
out = {{'ok': False, 'source_asset': asset_path, 'backup_asset': '', 'errors': []}}
try:
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        out['errors'].append('Source asset does not exist')
    else:
        asset_name = asset_path.rsplit('/', 1)[-1]
        backup_asset = backup_root.rstrip('/') + '/' + asset_name + '_backup_' + uuid.uuid4().hex[:8]
        copied = unreal.EditorAssetLibrary.duplicate_asset(asset_path, backup_asset)
        out['ok'] = bool(copied)
        out['backup_asset'] = backup_asset if copied else ''
        if copied:
            try:
                unreal.EditorAssetLibrary.save_asset(backup_asset)
            except Exception:
                pass
        else:
            out['errors'].append('duplicate_asset returned false')
except Exception as exc:
    out['errors'].append(str(exc))
print(json.dumps(out))
"""
        return self.execute_python(script, timeout=timeout, reset_globals=True)

    def apply_graph_patch(
        self, patch: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        script = f"""
import json, unreal
patch = json.loads({json.dumps(json.dumps(patch))})
out = {{
    'ok': False,
    'applied': False,
    'partial': False,
    'errors': [],
    'warnings': [],
    'validation_errors': [],
    'compile_errors': [],
    'compile_ok': False,
    'applied_operations': [],
    'created_nodes': [],
    'target_asset': patch.get('target_asset'),
    'target_graph': patch.get('target_graph'),
    'graph_snapshot_after': None,
}}

def _find_pin(node, pin_name):
    pins = []
    try:
        pins = unreal.BlueprintEditorLibrary.list_all_pins(node) or []
    except Exception:
        pins = list(getattr(node, 'pins', []) or [])
    wanted = str(pin_name or '').lower()
    aliases = {{
        'then': ['then', 'execute', 'exec'],
        'execute': ['execute', 'exec', 'then'],
        'instring': ['instring', 'in string', 'string'],
    }}.get(wanted, [wanted])
    for pin in pins:
        try:
            name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
        except Exception:
            try:
                name = str(pin.get_name())
            except Exception:
                name = ''
        if name.lower() in aliases:
            return pin
    return None

def _snapshot_graph(graph):
    graph_data = {{'name': str(graph.get_name()), 'nodes': []}}
    nodes = []
    try:
        bp_outer = graph.get_outer()
        graph_editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(bp_outer, str(graph.get_name()))
        nodes = unreal.BlueprintGraphEditor.list_all_nodes(graph_editor) or []
    except Exception:
        nodes = []
    for node in nodes:
        pins = []
        try:
            node_pins = unreal.BlueprintEditorLibrary.list_all_pins(node) or []
        except Exception:
            node_pins = list(getattr(node, 'pins', []) or [])
        for pin in node_pins:
            links = []
            try:
                linked_pins = unreal.BlueprintGraphPinLibrary.list_connected_pins(pin) or []
                for linked in linked_pins:
                    owner = unreal.BlueprintGraphPinLibrary.get_owning_node(linked)
                    links.append({{'node': str(owner.get_name()) if owner else '', 'pin': str(unreal.BlueprintGraphPinLibrary.get_pin_name(linked))}})
            except Exception:
                pass
            try:
                pin_name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
            except Exception:
                pin_name = str(pin.get_name()) if hasattr(pin, 'get_name') else ''
            try:
                pin_direction = str(unreal.BlueprintGraphPinLibrary.get_pin_direction(pin))
            except Exception:
                pin_direction = str(getattr(pin, 'direction', ''))
            try:
                pin_value = str(unreal.BlueprintGraphPinLibrary.get_pin_value(pin))
            except Exception:
                pin_value = ''
            pins.append({{'name': pin_name, 'direction': pin_direction, 'value': pin_value, 'linked_to': links}})
        graph_data['nodes'].append({{'name': str(node.get_name()), 'class': str(node.get_class().get_name()), 'pins': pins}})
    return graph_data

try:
    asset_path = patch.get('target_asset') or ''
    target_graph_name = patch.get('target_graph') or ''
    bp = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not bp:
        out['errors'].append('Target asset could not be loaded')
    else:
        try:
            subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            if subsystem:
                subsystem.open_editor_for_assets([bp])
        except Exception as open_exc:
            out['warnings'].append('Open editor before graph patch failed: ' + str(open_exc))
        graphs = unreal.BlueprintEditorLibrary.list_graphs(bp)
        target_graph = None
        for graph in graphs:
            if str(graph.get_name()) == target_graph_name:
                target_graph = graph
                break
        if not target_graph:
            out['errors'].append('Target graph not found')
        else:
            target_graph_editor = None
            try:
                target_graph_editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(bp, target_graph_name)
            except Exception as editor_exc:
                out['errors'].append('Target graph editor unavailable: ' + str(editor_exc))
            for op in patch.get('operations') or []:
                graph_nodes = []
                if target_graph_editor:
                    try:
                        graph_nodes = unreal.BlueprintGraphEditor.list_all_nodes(target_graph_editor) or []
                    except Exception as nodes_exc:
                        out['errors'].append('Node list failed before operation: ' + str(nodes_exc))
                        break
                nodes_by_name = {{str(node.get_name()): node for node in graph_nodes}}
                op_name = op.get('op')
                if op_name == 'remove_node':
                    node = nodes_by_name.get(op.get('node') or '')
                    if not node:
                        out['errors'].append('Node not found for removal: ' + str(op.get('node')))
                        break
                    unreal.BlueprintEditorLibrary.remove_node(bp, node, True)
                    out['applied_operations'].append(op)
                elif op_name == 'set_property':
                    node = nodes_by_name.get(op.get('node') or '')
                    if not node:
                        out['errors'].append('Node not found for property change: ' + str(op.get('node')))
                        break
                    try:
                        node.set_editor_property(op.get('property_name'), op.get('property_value'))
                    except Exception as prop_exc:
                        out['errors'].append('Property set failed: ' + str(prop_exc))
                        break
                    out['applied_operations'].append(op)
                elif op_name in ('connect_pins', 'disconnect_pins'):
                    src = nodes_by_name.get(op.get('from_node') or '')
                    dst = nodes_by_name.get(op.get('to_node') or '')
                    if not src or not dst:
                        out['errors'].append('Source or target node missing for pin operation')
                        break
                    src_pin = _find_pin(src, op.get('from_pin'))
                    dst_pin = _find_pin(dst, op.get('to_pin'))
                    if not src_pin or not dst_pin:
                        out['errors'].append('Source or target pin missing for pin operation')
                        break
                    try:
                        if op_name == 'connect_pins':
                            src_pin.make_link_to(dst_pin)
                        else:
                            src_pin.break_link_to(dst_pin)
                    except Exception as pin_exc:
                        out['errors'].append('Pin operation failed: ' + str(pin_exc))
                        break
                    out['applied_operations'].append(op)
                elif op_name == 'add_node':
                    node_class_name = str(op.get('node_class') or '')
                    new_node = None
                    source_node = None
                    try:
                        graph_schema = target_graph.get_schema() if hasattr(target_graph, 'get_schema') else None
                    except Exception:
                        graph_schema = None
                    spawn_error = None
                    try:
                        if op.get('from_node'):
                            source_node = nodes_by_name.get(op.get('from_node') or '')
                    except Exception:
                        source_node = None
                    if 'K2Node_Knot' in node_class_name or node_class_name.endswith('.K2Node_Knot'):
                        try:
                            new_node = unreal.BlueprintEditorLibrary.add_reroute_node(bp, target_graph, 0.0, 0.0)
                        except Exception as knot_exc:
                            spawn_error = knot_exc
                            if not hasattr(unreal.BlueprintEditorLibrary, 'add_reroute_node'):
                                out['warnings'].append(
                                    'Unreal Python does not expose BlueprintEditorLibrary.add_reroute_node in this editor session; '
                                    'reroute creation needs a reflected AIStudioBridge C++ wrapper capability before it can be applied safely.'
                                )
                    elif node_class_name in ('Development|PrintString', 'Development|Print String') and target_graph_editor:
                        try:
                            location = unreal.Vector2D(300.0, 0.0)
                            if source_node:
                                try:
                                    source_pos = unreal.BlueprintEditorLibrary.get_node_pos(source_node)
                                    location = unreal.Vector2D(float(source_pos.x) + 300.0, float(source_pos.y))
                                except Exception:
                                    pass
                            new_node = unreal.BlueprintGraphEditor.create_node_from_name(
                                target_graph_editor,
                                'Development|PrintString',
                                location,
                                [],
                                None,
                            )
                            try:
                                unreal.BlueprintEditorLibrary.set_node_pos(new_node, unreal.IntPoint(int(location.x), int(location.y)))
                            except Exception:
                                pass
                        except Exception as print_exc:
                            spawn_error = print_exc
                    elif 'K2Node_CallFunction' in node_class_name or node_class_name.endswith('.K2Node_CallFunction'):
                        out['warnings'].append('add_node for K2Node_CallFunction requires explicit function binding support; skipped for safety')
                    else:
                        out['warnings'].append('add_node unsupported for live apply class: ' + node_class_name)
                    if new_node:
                        desired_name = str(op.get('node') or '')
                        actual_name = str(new_node.get_name())
                        try:
                            pins = unreal.BlueprintEditorLibrary.list_all_pins(new_node) or []
                        except Exception:
                            pins = list(getattr(new_node, 'pins', []) or [])
                        if op.get('property_value') is not None:
                            for pin in pins:
                                try:
                                    pin_name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
                                except Exception:
                                    try:
                                        pin_name = str(pin.get_name())
                                    except Exception:
                                        pin_name = ''
                                if pin_name in (str(op.get('property_name') or ''), 'InString'):
                                    try:
                                        unreal.BlueprintGraphPinLibrary.set_pin_value(pin, str(op.get('property_value')))
                                    except Exception as pin_value_exc:
                                        out['warnings'].append('Set PrintString pin value failed: ' + str(pin_value_exc))
                        if source_node and op.get('from_pin') and op.get('to_pin'):
                            src_pin = _find_pin(source_node, op.get('from_pin'))
                            dst_pin = _find_pin(new_node, op.get('to_pin'))
                            if not src_pin or not dst_pin:
                                out['warnings'].append('Could not find requested pins to connect new node')
                            else:
                                try:
                                    connected = unreal.BlueprintGraphPinLibrary.try_create_connection(src_pin, dst_pin)
                                    if not connected:
                                        out['warnings'].append('try_create_connection returned false for new node')
                                except Exception as connect_exc:
                                    out['warnings'].append('Connecting new node failed: ' + str(connect_exc))
                        out['created_nodes'].append({{'requested_name': desired_name, 'actual_name': actual_name, 'class': node_class_name}})
                        out['applied_operations'].append(op)
                    elif spawn_error:
                        out['warnings'].append('add_node failed safely: ' + str(spawn_error))
                    else:
                        out['partial'] = True
                else:
                    out['errors'].append('Unsupported op: ' + str(op_name))
                    break
            try:
                unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                out['compile_ok'] = True
            except Exception as compile_exc:
                out['compile_errors'].append(str(compile_exc))
            try:
                unreal.EditorAssetLibrary.save_asset(asset_path)
            except Exception as save_exc:
                out['warnings'].append('Save raised: ' + str(save_exc))
            try:
                out['graph_snapshot_after'] = _snapshot_graph(target_graph)
            except Exception as snapshot_exc:
                out['warnings'].append('Post-apply graph snapshot failed: ' + str(snapshot_exc))
            out['ok'] = not out['errors'] and not out['compile_errors']
            out['applied'] = len(out['applied_operations']) > 0
except Exception as exc:
    out['errors'].append(str(exc))
print(json.dumps(out))
"""
        return self.execute_python(script, timeout=timeout, reset_globals=True)

    def restore_blueprint_backup(
        self,
        backup_asset_path: str,
        target_asset_path: str,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        script = f"""
import json, unreal
backup_asset_path = {backup_asset_path!r}
target_asset_path = {target_asset_path!r}
out = {{'ok': False, 'backup_asset': backup_asset_path, 'target_asset': target_asset_path, 'errors': []}}
try:
    if not unreal.EditorAssetLibrary.does_asset_exist(backup_asset_path):
        out['errors'].append('Backup asset does not exist')
    else:
        deleted = True
        if unreal.EditorAssetLibrary.does_asset_exist(target_asset_path):
            deleted = unreal.EditorAssetLibrary.delete_asset(target_asset_path)
        if not deleted:
            out['errors'].append('Existing target asset could not be removed before restore')
        else:
            restored = unreal.EditorAssetLibrary.duplicate_asset(backup_asset_path, target_asset_path)
            out['ok'] = bool(restored)
            if not restored:
                out['errors'].append('duplicate_asset returned false during restore')
            else:
                try:
                    unreal.EditorAssetLibrary.save_asset(target_asset_path)
                except Exception:
                    pass
except Exception as exc:
    out['errors'].append(str(exc))
print(json.dumps(out))
"""
        return self.execute_python(script, timeout=timeout, reset_globals=True)

    def health_check(self, timeout: float = 1.5) -> dict[str, Any]:
        port = self.find_port(self.HOST)
        cache_key = f"health:{port or 'offline'}"
        cached = self._health_cache.get(cache_key, 5.0)
        if cached is not None:
            data = dict(cached)
            data["used_memory_cache"] = True
            return data

        started = time.monotonic()
        checked_at = iso_now()
        result = {
            "connected": False,
            "port": None,
            "host": self.HOST,
            "latency_ms": None,
            "engine_version": None,
            "project_dir": None,
            "project_name": None,
            "loaded_level": None,
            "selected_actors": [],
            "selected_assets": [],
            "plugin_info": {},
            "python_available": False,
            "bridge_reachable": False,
            "error": None,
            "warnings": [],
            "checked_at": checked_at,
            "used_memory_cache": False,
            "checks": [],
        }

        result["port"] = port
        if not port:
            result["error"] = (
                f"Unreal HTTP bridge not found on port {self.DEFAULT_PORT}."
            )
            result["checks"].append(
                {
                    "name": "bridge_connected",
                    "ok": False,
                    "error": result["error"],
                    "duration_ms": elapsed_ms(started),
                }
            )
            self._health_cache.set(cache_key, dict(result))
            return result

        try:
            socket_started = time.monotonic()
            with socket.create_connection((self.HOST, port), timeout=timeout):
                result["connected"] = True
                result["bridge_reachable"] = True
                result["latency_ms"] = elapsed_ms(socket_started)
                result["checks"].append(
                    {
                        "name": "bridge_connected",
                        "ok": True,
                        "port": port,
                        "duration_ms": result["latency_ms"],
                    }
                )
        except Exception as exc:
            result["error"] = f"Socket connection failed: {exc}"
            result["checks"].append(
                {
                    "name": "bridge_connected",
                    "ok": False,
                    "error": result["error"],
                    "duration_ms": elapsed_ms(started),
                }
            )
            self._health_cache.set(cache_key, dict(result))
            return result

        python_probe_started = time.monotonic()
        python_probe = self.execute_python(
            "import json\nprint(json.dumps({'python_available': True}))",
            timeout=min(timeout, 1.5),
        )
        if python_probe["ok"]:
            result["python_available"] = True
            result["checks"].append(
                {
                    "name": "python_available",
                    "ok": True,
                    "duration_ms": elapsed_ms(python_probe_started),
                }
            )
        else:
            result["checks"].append(
                {
                    "name": "python_available",
                    "ok": False,
                    "error": python_probe.get("error"),
                    "duration_ms": elapsed_ms(python_probe_started),
                }
            )

        probe_started = time.monotonic()
        probe = self.safe_call(
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            args=["Skeleton", "/Game/"],
            timeout=min(timeout, 1.5),
            retries=0,
            retry_safe=True,
            label="health:known_tool",
            operation="health_known_tool",
        )
        if probe["ok"]:
            result["connected"] = True
            result["bridge_probe"] = "unreal_tools.get_skeletons.get_all_assets_of_type"
            result["bridge_probe_count"] = (
                len(probe.get("result") or {})
                if isinstance(probe.get("result"), dict)
                else None
            )
            result["bridge_probe_assets"] = (
                list((probe.get("result") or {}).keys())
                if isinstance(probe.get("result"), dict)
                else []
            )
            result["checks"].append(
                {
                    "name": "package_import",
                    "ok": True,
                    "package": "unreal_tools",
                    "duration_ms": probe.get("duration_ms"),
                }
            )
            result["checks"].append(
                {
                    "name": "skeleton_probe",
                    "ok": True,
                    "count": result["bridge_probe_count"],
                    "duration_ms": elapsed_ms(probe_started),
                }
            )
            result["error"] = None
        else:
            result["connected"] = False
            result["error"] = (
                probe.get("error") or "Known Unreal bridge tool probe failed."
            )
            result["checks"].append(
                {
                    "name": "package_import",
                    "ok": False,
                    "package": "unreal_tools",
                    "error": result["error"],
                    "duration_ms": probe.get("duration_ms"),
                }
            )
            result["checks"].append(
                {
                    "name": "skeleton_probe",
                    "ok": False,
                    "error": result["error"],
                    "duration_ms": elapsed_ms(probe_started),
                }
            )
            self._health_cache.set(cache_key, dict(result))
            return result

        check_started = time.monotonic()
        call = self.safe_call(
            "unreal_tools.level.scan_loaded_level",
            kwargs={"include_components": False, "max_actors": 1},
            timeout=0.6,
            retries=0,
            retry_safe=True,
            label="health:loaded_level",
            operation="health_loaded_level",
        )
        if call["ok"]:
            value = call.get("result")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    pass
            if isinstance(value, dict):
                result["loaded_level"] = (
                    value.get("current_level") or value.get("level_name") or None
                )
                selected = value.get("selected_actors")
                if isinstance(selected, list):
                    result["selected_actors"] = [str(item) for item in selected]
            else:
                result["loaded_level"] = str(value) if value is not None else None
            result["checks"].append(
                {
                    "name": "level_scan",
                    "ok": True,
                    "duration_ms": elapsed_ms(check_started),
                }
            )
        else:
            result["checks"].append(
                {
                    "name": "level_scan",
                    "ok": False,
                    "error": call.get("error"),
                    "duration_ms": elapsed_ms(check_started),
                }
            )

        trivial_started = time.monotonic()
        trivial = self.execute_python(
            "import json\nprint(json.dumps({'ok': True, 'ping': 'pong'}))",
            timeout=min(timeout, 1.5),
        )
        result["checks"].append(
            {
                "name": "trivial_command",
                "ok": bool(trivial.get("ok")),
                "error": trivial.get("error"),
                "duration_ms": elapsed_ms(trivial_started),
            }
        )

        state_started = time.monotonic()
        state_script = """
import json, unreal
state = {
    'engine_version': None,
    'project_name': None,
    'project_dir': None,
    'loaded_level': None,
    'loaded_level_short': None,
    'selected_assets': [],
    'selected_actors': [],
    'plugins': [],
    'warnings': [],
}
try:
    state['engine_version'] = unreal.SystemLibrary.get_engine_version()
except Exception as exc:
    state['warnings'].append('engine_version:' + str(exc))
try:
    project_file = unreal.Paths.get_project_file_path()
    state['project_dir'] = project_file or None
    if project_file:
        state['project_name'] = unreal.Paths.get_base_filename(project_file)
except Exception as exc:
    state['warnings'].append('project_name:' + str(exc))
try:
    world = unreal.EditorLevelLibrary.get_editor_world()
    if world:
        state['loaded_level'] = world.get_path_name() if hasattr(world, 'get_path_name') else world.get_name()
        raw_name = state['loaded_level'] or ''
        if raw_name:
            state['loaded_level_short'] = str(raw_name).replace('\\\\', '/').rsplit('/', 1)[-1].split('.')[-1]
except Exception as exc:
    state['warnings'].append('loaded_level:' + str(exc))
try:
    state['selected_assets'] = [str(a.get_path_name()) if hasattr(a, 'get_path_name') else str(a) for a in unreal.EditorUtilityLibrary.get_selected_assets()]
except Exception as exc:
    state['warnings'].append('selected_assets:' + str(exc))
try:
    state['selected_actors'] = [str(a.get_path_name()) if hasattr(a, 'get_path_name') else str(a) for a in unreal.EditorLevelLibrary.get_selected_level_actors()]
except Exception as exc:
    state['warnings'].append('selected_actors:' + str(exc))
try:
    state['plugins'] = [p.get_name() if hasattr(p, 'get_name') else (str(p.name) if hasattr(p, 'name') else str(p)) for p in unreal.PluginBlueprintLibrary.get_enabled_plugins()]
except Exception as exc:
    state['warnings'].append('plugins:' + str(exc))
print(json.dumps(state))
"""
        state_call = self.execute_python(
            state_script,
            timeout=min(timeout, 2.0),
        )
        if state_call.get("ok") and isinstance(state_call.get("data"), dict):
            state = state_call.get("data") or {}
            result["engine_version"] = result.get("engine_version") or state.get(
                "engine_version"
            )
            result["project_name"] = result.get("project_name") or state.get(
                "project_name"
            )
            result["project_dir"] = result.get("project_dir") or state.get(
                "project_dir"
            )
            result["loaded_level"] = (
                state.get("loaded_level_short")
                or result.get("loaded_level")
                or state.get("loaded_level")
            )
            result["selected_assets"] = [
                str(x) for x in state.get("selected_assets") or []
            ]
            result["selected_actors"] = [
                str(x) for x in state.get("selected_actors") or []
            ]
            result["plugin_info"] = {
                "enabled_plugins": [str(x) for x in state.get("plugins") or []]
            }
            if state.get("warnings"):
                result.setdefault("warnings", []).extend(
                    str(x) for x in (state.get("warnings") or [])
                )
            result["checks"].append(
                {
                    "name": "editor_state",
                    "ok": True,
                    "duration_ms": elapsed_ms(state_started),
                }
            )
        else:
            result["checks"].append(
                {
                    "name": "editor_state",
                    "ok": False,
                    "error": state_call.get("error"),
                    "duration_ms": elapsed_ms(state_started),
                }
            )

        project_dir = result.get("project_dir")
        if project_dir:
            try:
                result["project_name"] = os.path.basename(
                    str(project_dir).rstrip("/\\")
                )
            except Exception:
                pass

        result["latency_ms"] = result["latency_ms"] or elapsed_ms(started)
        self._health_cache.set(cache_key, dict(result))
        return result

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict[str, Any]:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Unreal HTTP bridge found."}
        bridge = self if self._forced_port == port else type(self)(forced_port=port)
        health = dict(bridge.health_check(timeout=timeout) or {})
        health["ok"] = bool(health.get("connected") and health.get("python_available"))
        health["port"] = port
        return health

    def sessions(self, host=HOST) -> list[dict[str, Any]]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def call(
        self,
        function_path: str,
        args=None,
        kwargs=None,
        timeout: float = 30,
        retries: int = 1,
        retry_safe: bool | None = None,
        operation: str | None = None,
    ) -> tuple[bool, str]:
        response = self.safe_call(
            function_path,
            args=args or [],
            kwargs=kwargs or {},
            timeout=timeout,
            retries=retries,
            retry_safe=retry_safe,
            operation=operation or function_path,
        )
        if response["ok"]:
            value = response.get("data")
            if isinstance(value, (dict, list)):
                return True, json.dumps(value, indent=2, default=str)
            return True, "" if value is None else str(value)
        error = response.get("error") or "Unreal bridge call failed."
        raw = response.get("raw") or ""
        if raw:
            return False, raw
        return False, error


    def object_resolver(self):
        """Return the typed Unreal object resolver bound to this bridge."""
        try:
            from tech_connector.services.unreal.unreal_resolvers import UnrealObjectResolver
        except Exception:
            try:
                from unreal_resolvers import UnrealObjectResolver
            except Exception as exc:
                raise RuntimeError(f"Unreal resolver unavailable: {exc}") from exc
        return UnrealObjectResolver(self)

    def resolve_object(
        self,
        kind: str,
        query: str = "selected",
        *,
        expected_class: str = "",
        owner: str = "selected",
        component_class: str = "",
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        """Resolve a natural-language/string target into a typed Unreal handle.

        This runs the lookup inside Unreal so type-sensitive APIs can later be
        called with real UObject/Actor/Component values instead of plain strings.
        """
        resolver = self.object_resolver()
        key = (kind or "").strip().lower()
        if key in {"asset", "uasset", "object"}:
            return resolver.resolve_asset(query, expected_class=expected_class, timeout=timeout)
        if key in {"actor", "level_actor"}:
            return resolver.resolve_actor(query, timeout=timeout)
        if key in {"component", "actor_component"}:
            return resolver.resolve_component(owner, query, component_class, timeout=timeout)
        if key in {"control_rig", "controlrig", "control_rig_class"}:
            return resolver.resolve_control_rig(query, timeout=timeout)
        return {"ok": False, "error": f"Unsupported Unreal resolver kind: {kind}", "query": query}

    def select_actors_resolved(self, query: str | list[str], timeout: float = 5.0) -> dict[str, Any]:
        """Resolve actor names/assets/classes into live Actor objects and select them."""
        return self.object_resolver().select_actors(query, timeout=timeout)

    def set_actor_property_resolved(
        self,
        actor_query: str,
        property_name: str,
        value: Any,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Resolve an actor target, then set an editor property on the live Actor."""
        return self.object_resolver().set_actor_property(
            actor_query, property_name, value, timeout=timeout
        )

    def call_resolved(
        self,
        function_path: str,
        *,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        contracts: list[dict[str, Any]] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call a host function after satisfying typed argument contracts.

        Contract example:
            {"name": "actor", "kind": "actor", "source": "selected"}
            {"name": "asset_path", "kind": "asset_path", "source": "Run_Fwd", "expected_class": "AnimSequence"}
        """
        return self.object_resolver().call_function_resolved(
            function_path,
            args=args or [],
            kwargs=kwargs or {},
            contracts=contracts or [],
            timeout=timeout,
        )

    def parse_input(self, text: str) -> tuple[str, str, list, dict]:
        """
        Parse function path or JSON payload.
        Returns (function_path, args, kwargs).
        """
        if text.startswith("{"):
            data = json.loads(text)
            return data["function"], data.get("args", []), data.get("kwargs", {})
        return text.strip(), [], {}
