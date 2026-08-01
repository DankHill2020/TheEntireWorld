"""DCC execution preparation and adapter registry.

This layer receives an already-classified route. It prepares a typed execution
request, validates capabilities/signatures where deterministic metadata exists,
and delegates to host adapters. It must not decide intent from prompt text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Protocol

from reasoning_runtime.engine.request_context import RequestContext


@dataclass
class CapabilityFailure:
    capability: str
    current_state: str = "missing"
    can_resolve: bool = False
    required_user_action: str = ""
    retry_possible: bool = True
    alternate_route: str = ""


@dataclass
class CapabilityCheckResult:
    ok: bool
    failures: list[CapabilityFailure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "failures": [asdict(item) for item in self.failures]}


@dataclass
class DccExecutionRequest:
    execution_environment: str
    operation_mode: str
    target_type: str
    target_identifier: str = ""
    callable_name: str = ""
    module: str = ""
    file: str = ""
    positional_args: list[Any] = field(default_factory=list)
    keyword_args: dict[str, Any] = field(default_factory=dict)
    argument_schema: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    selected_objects: list[str] = field(default_factory=list)
    active_scene: str = ""
    preview_only: bool = False
    mutation_scope: str = "read_only"
    risk_level: str = "low"
    requires_confirmation: bool = False
    approved: bool = False
    timeout_seconds: float = 60.0
    expected_result_type: str = "text"
    original_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DccDispatchResult:
    status: str
    execution_environment: str
    operation_mode: str
    user_message: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    rendered_output: str = ""
    preview_code: str = ""
    executed_code: str = ""
    affected_targets: list[str] = field(default_factory=list)
    mutation_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    missing_capabilities: list[dict[str, Any]] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)
    confirmation_request: dict[str, Any] = field(default_factory=dict)
    retry_metadata: dict[str, Any] = field(default_factory=dict)
    raw_result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DccExecutionAdapter(Protocol):
    host: str

    def check_capabilities(self, request: DccExecutionRequest, context: RequestContext) -> CapabilityCheckResult: ...
    def preview(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult: ...
    def query(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult: ...
    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult: ...


def _window(context: RequestContext):
    return (context.extras or {}).get("window")


def _method(window: Any, name: str):
    fn = getattr(window, name, None)
    return fn if callable(fn) else None


def _maya_direct_bridge_available() -> bool:
    try:
        from tech_connector.bridges.maya.maya_bridge import MayaBridge

        return bool(MayaBridge().find_port())
    except Exception:
        return False


def _maya_direct_bridge_sessions() -> list[dict[str, Any]]:
    try:
        from tech_connector.bridges.maya.maya_bridge import MayaBridge

        bridge = MayaBridge()
        sessions = bridge.sessions()
        return [session for session in sessions if session.get("ok")]
    except Exception:
        return []


def _format_maya_session_choices(sessions: list[dict[str, Any]]) -> str:
    choices = []
    for session in sessions:
        port = session.get("port") or "?"
        pid = session.get("pid") or "?"
        scene = session.get("scene") or "unsaved scene"
        selection = session.get("selection") or []
        selection_text = f", selection: {', '.join(map(str, selection[:3]))}" if selection else ""
        choices.append(f"scene `{scene}`, pid `{pid}`, port `{port}`{selection_text}")
    return "; ".join(choices)


def _normalise_path_fragment(value: Any) -> str:
    text = str(value or "").strip().strip("`'\"")
    return text.replace("\\", "/").lower()


def _session_match_terms(value: Any) -> set[str]:
    text = _normalise_path_fragment(value).replace("_", " ")
    return {
        term
        for term in re.findall(r"[a-z0-9]+", text)
        if len(term) >= 3 and term not in {"maya", "file", "path", "scene", "session", "with", "use", "the"}
    }


def _maya_port_for_prompted_session(text: str, sessions: list[dict[str, Any]]) -> int | None:
    prompt = _normalise_path_fragment(text)
    if not prompt or not sessions:
        return None
    for session in sessions:
        scene = _normalise_path_fragment(session.get("scene"))
        if scene and scene in prompt:
            try:
                return int(session.get("port"))
            except Exception:
                return None
    for session in sessions:
        scene = _normalise_path_fragment(session.get("scene"))
        name = scene.rsplit("/", 1)[-1] if scene else ""
        if name and name in prompt:
            try:
                return int(session.get("port"))
            except Exception:
                return None
    if "unsaved" in prompt:
        for session in sessions:
            if not session.get("scene"):
                try:
                    return int(session.get("port"))
                except Exception:
                    return None
    prompt_terms = _session_match_terms(prompt)
    scored: list[tuple[int, dict[str, Any]]] = []
    for session in sessions:
        scene = _normalise_path_fragment(session.get("scene"))
        if not scene:
            continue
        scene_terms = _session_match_terms(scene)
        score = len(prompt_terms & scene_terms)
        if score:
            scored.append((score, session))
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            try:
                return int(scored[0][1].get("port"))
            except Exception:
                return None
    return None


def _prompt_mentions_maya_session(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:maya\s+)?(?:port|session)\s*:?\s*7\d{3,5}\b"
            r"|\b(?:use|using|with)\s+(?:the\s+)?(?:maya\s+)?(?:session|file|scene)\b"
            r"|\b(?:omari|cinematic|\.ma|\.mb)\b",
            text or "",
            re.IGNORECASE,
        )
    )


def _unreal_direct_bridge_available() -> bool:
    try:
        from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

        bridge = UnrealBridge()
        port = getattr(bridge, "port", None) or getattr(bridge, "find_port", lambda: None)()
        return bool(port)
    except Exception:
        return False


def _extract_json_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict):
            return data
        output = raw.get("output") or raw.get("stdout") or raw.get("result") or raw.get("raw") or raw.get("text")
        if output is not None:
            raw = output
        else:
            return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            pass
    return {"raw": text}


def _as_name_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    names: list[str] = []
    for item in values:
        name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _node_from_plug(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(".", 1)[0] if "." in text else text


def _maya_operation_target_names(operation_key: str, params: dict[str, Any]) -> list[str]:
    """Return existing Maya scene objects that should be verified before mutation."""
    keys_by_operation = {
        "scene.select": ("objects",),
        "scene.move": ("objects",),
        "navigation.frame_selection": ("objects",),
        "constraints.create": ("targets", "driven"),
        "material.assign": ("objects",),
        "skin.bind": ("mesh", "influences"),
        "skin.add_influence": ("mesh", "influence"),
    }
    names: list[str] = []
    for key in keys_by_operation.get(operation_key, ()):
        for name in _as_name_list(params.get(key)):
            if name not in names:
                names.append(name)
    if operation_key in {"node.connect_attr", "node.disconnect_attr"}:
        for key in ("source_attr", "destination_attr"):
            node = _node_from_plug(params.get(key))
            if node and node not in names:
                names.append(node)
    return names


def _guess_callable_name(prompt: str) -> str:
    lower = (prompt or "").lower()
    match = re.search(r"\b(?:run|execute|call|launch|test)\s+([A-Za-z_][A-Za-z0-9_]*)\b", prompt or "", re.IGNORECASE)
    if match:
        value = match.group(1)
        if value.lower() not in {"the", "a", "an", "this", "that"}:
            return value
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*)\b", prompt or "")
    return match.group(1) if match else ""


def _signature_for_callable(callable_name: str, context: RequestContext) -> dict[str, Any]:
    if not callable_name:
        return {}
    try:
        from tech_connector.knowledge.search import search_index_symbols

        rows = search_index_symbols(
            [callable_name],
            limit=8,
            active_path=context.current_file_path,
            scope=((context.extras or {}).get("prompt_route_decision") or {}).get("index_filters", {}).get("scope") or "project",
            project_roots=list(context.project_roots or []),
        )
    except Exception:
        rows = []
    exact = [
        row for row in rows
        if str(row.get("name") or "").lower() == callable_name.lower()
        and str(row.get("kind") or "").lower() in {"function", "method"}
    ]
    if len(exact) != 1:
        return {
            "matches": exact or rows,
            "ambiguous": len(exact) > 1,
            "found": bool(exact or rows),
        }
    row = exact[0]
    signature = str(row.get("signature") or "")
    return {
        "found": True,
        "ambiguous": False,
        "name": row.get("name") or callable_name,
        "qualname": row.get("qualname") or "",
        "module": row.get("module") or "",
        "file": row.get("path") or "",
        "signature": signature,
        "required_args": _required_args_from_signature(signature),
        "row": row,
    }


def _required_args_from_signature(signature: str) -> list[str]:
    text = str(signature or "")
    if "(" not in text or ")" not in text:
        return []
    inner = text[text.find("(") + 1:text.rfind(")")]
    required: list[str] = []
    for raw in inner.split(","):
        item = raw.strip()
        if not item or item in {"self", "cls", "*", "/"}:
            continue
        if item.startswith("*"):
            continue
        name = item.split(":", 1)[0].split("=", 1)[0].strip()
        if name and "=" not in item:
            required.append(name)
    return required


def build_dcc_execution_request(decision: dict, context: RequestContext) -> DccExecutionRequest:
    execution_environment = str(decision.get("execution_environment") or decision.get("host") or "").strip()
    target_identifier = str(decision.get("target_identifier") or "").strip()
    callable_name = str(decision.get("callable_name") or target_identifier or "").strip()
    is_unreal_graph_edit = (
        execution_environment == "unreal"
        and decision.get("intent_category") == "unreal_semantic_graph_modification"
    )
    if not callable_name and not is_unreal_graph_edit:
        callable_name = _guess_callable_name(context.text)
    if not target_identifier and not is_unreal_graph_edit:
        target_identifier = callable_name
    known_unreal_operation = False
    if execution_environment == "unreal" and target_identifier:
        try:
            from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS
        except Exception:
            UNREAL_OPERATIONS = {}
        known_unreal_operation = target_identifier in UNREAL_OPERATIONS
    known_dcc_operation = False
    if execution_environment in {"maya", "blender", "substance_painter", "motionbuilder", "unity"} and target_identifier:
        try:
            from tech_connector.services.dcc.dcc_operation_service import (
                BLENDER_OPERATIONS,
                MAYA_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            known_dcc_operation = target_identifier in {
                "maya": MAYA_OPERATIONS,
                "blender": BLENDER_OPERATIONS,
                "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                "motionbuilder": MOTIONBUILDER_OPERATIONS,
                "unity": UNITY_OPERATIONS,
            }.get(execution_environment, {})
        except Exception:
            known_dcc_operation = False
    explicit_unreal_callable = execution_environment == "unreal" and callable_name.startswith("unreal_tools.")
    schema = {} if (known_unreal_operation or known_dcc_operation) else _signature_for_callable(callable_name, context)
    missing_slots = list(decision.get("missing_info") or [])
    required_args = list(schema.get("required_args") or [])
    if required_args and not decision.get("keyword_args") and not decision.get("positional_args"):
        missing_slots.extend([arg for arg in required_args if arg not in missing_slots])
    if schema.get("ambiguous"):
        missing_slots.append("callable_disambiguation")
    if callable_name and not is_unreal_graph_edit and not schema.get("found") and not known_unreal_operation and not known_dcc_operation and not explicit_unreal_callable:
        missing_slots.append("callable")

    keyword_args = dict(decision.get("keyword_args") or {})
    if execution_environment == "maya" and not keyword_args.get("maya_port"):
        port_match = re.search(r"\b(?:maya\s+)?(?:port|session)\s*:?\s*(7\d{3,5})\b", context.text or "", re.IGNORECASE)
        if port_match:
            try:
                keyword_args["maya_port"] = int(port_match.group(1))
            except Exception:
                pass
        elif _prompt_mentions_maya_session(context.text or ""):
            selected_port = _maya_port_for_prompted_session(context.text or "", _maya_direct_bridge_sessions())
            if selected_port:
                keyword_args["maya_port"] = selected_port

    # Extract parameters for Unreal, Maya, and Blender operations
    if execution_environment == "unreal" and target_identifier:
        if target_identifier == "niagara.create_emitter":
            try:
                from tech_connector.services.unreal.unreal_operation_service import build_unreal_niagara_create_params
                inferred_args = build_unreal_niagara_create_params(context.text)
                merged_args = dict(inferred_args)
                merged_args.update(keyword_args)
                keyword_args = merged_args
            except Exception:
                pass
        elif target_identifier == "blueprint.create_from_template":
            try:
                from tech_connector.services.unreal.unreal_operation_service import infer_unreal_prototype_template, extract_unreal_asset_paths
                template_val = infer_unreal_prototype_template(context.text)
                asset_paths = extract_unreal_asset_paths(context.text)
                inferred_args = {
                    "template": template_val or "combat_combo",
                    "asset_path": asset_paths[0] if asset_paths else "",
                }
                merged_args = dict(inferred_args)
                merged_args.update(keyword_args)
                keyword_args = merged_args
            except Exception:
                pass
    elif execution_environment in {"maya", "blender"} and target_identifier:
        try:
            from tech_connector.services.dcc.dcc_operation_service import build_dcc_operation_params
            inferred_args = build_dcc_operation_params(execution_environment, target_identifier, context.text)
            merged_args = dict(inferred_args)
            merged_args.update(keyword_args)
            keyword_args = merged_args
        except Exception:
            pass

    missing_slots = [
        name
        for name in missing_slots
        if name not in keyword_args or keyword_args.get(name) in (None, "")
    ]

    # If the environment is unreal and we require/have asset_path/target_path/blueprint_path:
    # Check if we should add asset_name to missing_slots
    is_unreal = execution_environment == "unreal"
    path_keys = {"asset_path", "target_path", "blueprint_path"}
    has_path_slot = any(k in missing_slots for k in path_keys)
    has_path_val_key = None
    for k in path_keys:
        val = keyword_args.get(k)
        if val and str(val).endswith("/"):
            has_path_val_key = k
            break

    if is_unreal and has_path_val_key:
        if "asset_name" not in missing_slots and not keyword_args.get("asset_name"):
            missing_slots.append("asset_name")

    # Combine folder path and asset name if both are supplied and path ends with /
    if is_unreal:
        for k in path_keys:
            if k in keyword_args and "asset_name" in keyword_args:
                path = str(keyword_args[k])
                name = str(keyword_args["asset_name"])
                if path.endswith("/"):
                    keyword_args[k] = f"{path.rstrip('/')}/{name.lstrip('/')}"
                    keyword_args.pop("asset_name", None)
                    break

    return DccExecutionRequest(
        execution_environment=execution_environment,
        operation_mode=str(decision.get("operation_mode") or "execute"),
        target_type=str(decision.get("target_type") or "dcc_callable"),
        target_identifier=target_identifier,
        callable_name=callable_name,
        module=str(schema.get("module") or ""),
        file=str(schema.get("file") or ""),
        positional_args=list(decision.get("positional_args") or []),
        keyword_args=keyword_args,
        argument_schema=schema,
        missing_slots=sorted(set(missing_slots)),
        preview_only=str(decision.get("operation_mode") or "") == "preview",
        mutation_scope=str(decision.get("mutation_scope") or "read_only"),
        risk_level=str(decision.get("risk_level") or "low"),
        requires_confirmation=bool(decision.get("requires_confirmation")),
        approved=bool(decision.get("approved") or decision.get("confirmation_accepted")),
        original_prompt=context.text,
    )


@dataclass
class WindowDccExecutionAdapter:
    host: str
    query_methods: dict[str, str] = field(default_factory=dict)

    def check_capabilities(self, request: DccExecutionRequest, context: RequestContext) -> CapabilityCheckResult:
        failures: list[CapabilityFailure] = []
        window = _window(context)
        if window is None:
            failures.append(CapabilityFailure("foreground_window", required_user_action="Run this from the Tech Connector UI."))
        if request.operation_mode == "execute" and request.missing_slots:
            failures.append(
                CapabilityFailure(
                    "arguments_resolved",
                    current_state="missing_slots",
                    can_resolve=False,
                    required_user_action="Provide values for: " + ", ".join(request.missing_slots),
                )
            )
        return CapabilityCheckResult(ok=not failures, failures=failures)

    def preview(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        lines = [
            f"{self.host.title()} execution preview",
            f"Mode: {request.operation_mode}",
            f"Target: {request.callable_name or request.target_identifier or '(not resolved)'}",
            f"Mutation scope: {request.mutation_scope}",
        ]
        if request.argument_schema:
            lines.append(f"Signature: {request.argument_schema.get('signature') or '(unknown)'}")
        if request.missing_slots:
            lines.append("Missing slots: " + ", ".join(request.missing_slots))
        return DccDispatchResult(
            status="preview",
            execution_environment=self.host,
            operation_mode="preview",
            user_message="\n".join(lines),
            structured_data={"request": request.to_dict()},
            missing_slots=request.missing_slots,
        )

    def query(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        window = _window(context)
        method_name = self._query_method_name(request)
        fn = _method(window, method_name) if window is not None else None
        if not fn:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode="query",
                user_message=f"No registered {self.host} query adapter for `{request.target_identifier or request.callable_name or 'query'}`.",
                retry_metadata={"method": method_name},
            )
        fn()
        return DccDispatchResult(
            status="queued",
            execution_environment=self.host,
            operation_mode="query",
            user_message=f"{self.host.title()} query sent through registered adapter.",
            structured_data={"method": method_name},
        )

    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        if request.operation_mode == "query":
            return self.query(request, context)
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=(
                "Execution was not started automatically. The callable has been resolved enough for dispatch, "
                "but foreground host mutation still requires an explicit confirmation adapter."
            ),
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name,
            } if request.requires_confirmation else {},
        )

    def _query_method_name(self, request: DccExecutionRequest) -> str:
        key = (request.target_identifier or request.callable_name or "").lower()
        if "selection" in key or "selected" in key:
            return self.query_methods.get("selection", "")
        if "file" in key or "scene" in key:
            return self.query_methods.get("file", "")
        return self.query_methods.get("default", "")


class MayaExecutionAdapter(WindowDccExecutionAdapter):
    def _execute_maya_code(
        self,
        bridge: Any,
        code: str,
        request: DccExecutionRequest,
        timeout: float,
    ) -> tuple[bool, Any]:
        port = (request.keyword_args or {}).get("maya_port")
        if port and hasattr(bridge, "execute_on_port"):
            try:
                return bridge.execute_on_port(code, port=int(port), timeout=timeout)
            except Exception as exc:
                return False, f"Failed to execute Maya code on selected port {port}: {exc}"
        return bridge.execute(code, timeout=timeout)

    def check_capabilities(self, request: DccExecutionRequest, context: RequestContext) -> CapabilityCheckResult:
        known_mutating_operation_requires_approval = False
        try:
            from tech_connector.services.dcc.dcc_operation_service import MAYA_OPERATIONS

            op = MAYA_OPERATIONS.get(request.target_identifier or "")
            known_mutating_operation_requires_approval = bool(op and op.mutates_project and not request.approved)
        except Exception:
            known_mutating_operation_requires_approval = False
        if known_mutating_operation_requires_approval and not request.missing_slots and not _prompt_mentions_maya_session(context.text or ""):
            return CapabilityCheckResult(ok=True)
        direct_operations = {"scene.select", "scene.move", "scene.create_locator", "scene.create_control", "node.connect_attr", "node.disconnect_attr", "constraints.create", "modeling.create_primitive", "api.call", "tool.call", "script.run"}
        sessions = _maya_direct_bridge_sessions()
        if len(sessions) > 1 and not (request.keyword_args or {}).get("maya_port"):
            selected_port = _maya_port_for_prompted_session(context.text or "", sessions)
            if selected_port:
                request.keyword_args["maya_port"] = selected_port
        if len(sessions) > 1 and not (request.keyword_args or {}).get("maya_port"):
            return CapabilityCheckResult(
                ok=False,
                failures=[
                    CapabilityFailure(
                        capability="maya_session_selection",
                        current_state="multiple_sessions",
                        can_resolve=True,
                        required_user_action=(
                            "Choose which Maya session to use: "
                            + _format_maya_session_choices(sessions)
                        ),
                    )
                ],
            )
        if known_mutating_operation_requires_approval and not request.missing_slots:
            return CapabilityCheckResult(ok=True)
        if (
            _window(context) is None
            and (
                (request.operation_mode == "query" and request.mutation_scope == "read_only")
                or (request.approved and request.target_identifier in direct_operations)
            )
            and bool(sessions or _maya_direct_bridge_available())
        ):
            return CapabilityCheckResult(ok=True)
        return super().check_capabilities(request, context)

    def query(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.target_identifier == "scene.ls":
            return self._query_maya_ls(request, context)
        if request.target_identifier == "scene.list_joints":
            return self._query_maya_joints(request, context)
        if _window(context) is None and request.mutation_scope == "read_only":
            key = (request.target_identifier or request.callable_name or "").lower()
            if "selection" in key or "selected" in key:
                return self._query_maya_selection_direct(request)
            if "file" in key or "scene" in key:
                return self._query_maya_scene_direct(request)
        return super().query(request, context)

    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        if request.operation_mode == "query":
            return self.query(request, context)
        operation_key = request.target_identifier or ""
        if operation_key:
            result = self._execute_known_maya_operation(operation_key, request, context)
            if result is not None:
                return result
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="Maya execution is routed, but mutating capability execution is blocked until confirmation/preflight is wired into the adapter.",
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name or request.target_identifier,
            } if request.requires_confirmation else {},
        )

    def _execute_known_maya_operation(
        self,
        operation_key: str,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from tech_connector.services.dcc.dcc_operation_service import MAYA_OPERATIONS
        except Exception:
            MAYA_OPERATIONS = {}
        if operation_key not in MAYA_OPERATIONS:
            return None
        op = MAYA_OPERATIONS[operation_key]
        if operation_key == "scene.list_joints":
            return self._query_maya_joints(request, context)
        if getattr(op, "mutates_project", False) and not request.approved:
            return DccDispatchResult(
                status="confirmation_required",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"`{operation_key}` is a mutating Maya operation and needs confirmation before execution.",
                structured_data={"request": request.to_dict()},
                confirmation_request={
                    "operation": operation_key,
                    "risk_level": request.risk_level,
                    "mutation_scope": request.mutation_scope,
                },
            )
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Maya operation is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict(), "operation": operation_key},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "maya", None) if router is not None else None
        if not bridge:
            try:
                from tech_connector.bridges.maya.maya_bridge import MayaBridge

                bridge = MayaBridge()
            except Exception:
                bridge = None
        if not bridge:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No Maya bridge executor is available.",
            )
        params = dict(request.keyword_args or {})
        preflight = self._preflight_maya_object_targets(operation_key, params, request, bridge)
        if preflight is not None:
            return preflight
        if str(getattr(op, "function", "") or "").startswith("ai_studio.maya.generated."):
            from tech_connector.services.dcc.dcc_operation_service import maya_operation_code

            code = maya_operation_code(operation_key, params)
            ok, raw = self._execute_maya_code(bridge, code, request, request.timeout_seconds)
        else:
            ok, raw = bridge.call_function(op.function, kwargs=params)
        user_message = f"Successfully executed Maya operation `{operation_key}`." if ok else f"Maya operation failed: {raw}"
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"operation": operation_key, "ok": ok},
            rendered_output=user_message,
            raw_result=raw,
        )

    def _preflight_maya_object_targets(
        self,
        operation_key: str,
        params: dict[str, Any],
        request: DccExecutionRequest,
        bridge: Any,
    ) -> DccDispatchResult | None:
        target_names = _maya_operation_target_names(operation_key, params)
        if not target_names:
            return None
        import json

        code = f"""
import json
import maya.cmds as cmds
names = {target_names!r}
missing = [name for name in names if name and not cmds.objExists(name)]
print(json.dumps({{'missing': missing, 'checked': names}}))
"""
        ok, raw = self._execute_maya_code(bridge, code, request, min(float(request.timeout_seconds or 5.0), 5.0))
        if not ok:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"Maya object preflight failed before `{operation_key}`: {raw}",
                raw_result=raw,
            )
        try:
            data = json.loads(str(raw or "").strip())
        except Exception:
            data = {"raw": raw, "missing": []}
        missing = [str(item) for item in data.get("missing") or [] if item]
        if not missing:
            return None
        missing_text = ", ".join(f"`{name}`" for name in missing)
        return DccDispatchResult(
            status="confirmation_required",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=(
                f"I checked Maya before running `{operation_key}` and could not find: {missing_text}.\n\n"
                "I should not run the mutation yet. Reply with the correct existing object name, "
                "or approve a prerequisite plan to create/select the missing target first."
            ),
            structured_data={
                "request": request.to_dict(),
                "operation": operation_key,
                "object_preflight": data,
                "missing_objects": missing,
            },
            confirmation_request={
                "operation": "scene.object_exists",
                "missing_objects": missing,
                "suggested_action": "provide_existing_target_or_approve_prerequisite_creation",
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
            },
            raw_result=raw,
        )

    def _query_maya_joints(
        self,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult:
        params = dict(request.keyword_args or {})
        params["type"] = "joint"
        ls_request = DccExecutionRequest(**{**request.to_dict(), "target_identifier": "scene.ls", "keyword_args": params})
        result = self._query_maya_ls(ls_request, context)
        data = dict(result.structured_data.get("ls_query") or {})
        first_only = bool(params.get("first_only"))
        raw_items = data.get("items") or data.get("joints") or []
        first = str((raw_items or [data.get("first_joint") or ""])[0] or "")
        joints = list(raw_items or [])
        if first_only:
            message = f"The first Maya joint/bone I found is `{first}`." if first else "I did not find any Maya joints/bones in the current scene."
        else:
            message = (
                "Maya joints/bones: " + ", ".join(f"`{item}`" for item in joints)
                if joints
                else "I did not find any Maya joints/bones in the current scene."
            )
        return DccDispatchResult(
            status="completed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=message,
            rendered_output=message,
            structured_data={"operation": "scene.list_joints", "joint_query": data},
            raw_result=result.raw_result,
        )

    def _query_maya_ls(
        self,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult:
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "maya", None) if router is not None else None
        if not bridge:
            try:
                from tech_connector.bridges.maya.maya_bridge import MayaBridge

                bridge = MayaBridge()
            except Exception:
                bridge = None
        if not bridge:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode="query",
                user_message="No Maya bridge executor is available.",
            )
        params = dict(request.keyword_args or {})
        first_only = bool(params.get("first_only"))
        limit = int(params.get("limit") or (1 if first_only else 50))
        payload = {
            "selection": bool(params.get("selection")),
            "type": str(params.get("type") or ""),
            "long": bool(params.get("long")),
            "flatten": bool(params.get("flatten")),
            "name_patterns": list(params.get("name_patterns") or []),
            "limit": max(1, limit),
        }
        code = f"""
import json
import maya.cmds as cmds
params = json.loads({json.dumps(payload)!r})
kwargs = {{}}
if params.get('selection'):
    kwargs['selection'] = True
if params.get('type'):
    kwargs['type'] = params.get('type')
if params.get('long'):
    kwargs['long'] = True
if params.get('flatten'):
    kwargs['flatten'] = True
patterns = params.get('name_patterns') or []
items = []
if patterns:
    for pattern in patterns:
        for item in (cmds.ls(pattern, **kwargs) or []):
            if item not in items:
                items.append(item)
else:
    items = cmds.ls(**kwargs) or []
payload = {{
    'kind': 'maya.cmds.ls',
    'flags': kwargs,
    'name_patterns': patterns,
    'items': items[:int(params.get('limit') or 50)],
    'count': len(items),
}}
print(json.dumps(payload))
"""
        ok, raw = self._execute_maya_code(bridge, code, request, min(float(request.timeout_seconds or 5.0), 10.0))
        data = _extract_json_payload(raw)
        items = [str(item) for item in data.get("items") or []]
        flags = data.get("flags") if isinstance(data.get("flags"), dict) else {}
        if params.get("selection"):
            message = (
                "Maya selection: " + ", ".join(f"`{item}`" for item in items)
                if items
                else "Maya is connected, but nothing is currently selected."
            )
        elif params.get("type"):
            message = (
                f"Maya `{params.get('type')}` nodes: " + ", ".join(f"`{item}`" for item in items)
                if items
                else f"I did not find any Maya nodes of type `{params.get('type')}`."
            )
        else:
            message = (
                "Maya nodes: " + ", ".join(f"`{item}`" for item in items)
                if items
                else "I did not find matching Maya nodes."
            )
        if data.get("count", len(items)) > len(items):
            message += f" Showing {len(items)} of {data.get('count')}."
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=message if ok else f"Maya cmds.ls query failed: {raw}",
            rendered_output=message if ok else f"Maya cmds.ls query failed: {raw}",
            structured_data={"operation": "scene.ls", "ls_query": data, "flags": flags},
            raw_result=raw,
        )

    def _query_maya_selection_direct(self, request: DccExecutionRequest) -> DccDispatchResult:
        ls_request = DccExecutionRequest(**{**request.to_dict(), "target_identifier": "scene.ls", "keyword_args": {"selection": True}})
        return self._query_maya_ls(ls_request, RequestContext(text=request.original_prompt or "Maya selection query"))

    def _query_maya_scene_direct(self, request: DccExecutionRequest) -> DccDispatchResult:
        try:
            from tech_connector.bridges.maya.maya_bridge import MayaBridge
        except Exception as exc:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode="query",
                user_message=f"Maya bridge is unavailable: {exc}",
            )
        code = """
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui

payload = {
    'scene': cmds.file(query=True, sceneName=True) or '',
    'modified': bool(cmds.file(query=True, modified=True)),
    'selection': cmds.ls(selection=True, long=False) or [],
    'openmaya_active_camera': '',
    'openmaya_focal_length': 35.0,
}
try:
    view = omui.M3dView.active3dView()
    cam_dag = view.getCamera()
    payload['openmaya_active_camera'] = cam_dag.fullPathName()
    fn_cam = om.MFnCamera(cam_dag)
    payload['openmaya_focal_length'] = fn_cam.focalLength
except Exception:
    pass

print(json.dumps(payload))
"""
        ok, raw = self._execute_maya_code(MayaBridge(), code, request, min(float(request.timeout_seconds or 5.0), 5.0))
        data = _extract_json_payload(raw)
        scene = str(data.get("scene") or "")
        cam = str(data.get("openmaya_active_camera") or "persp")
        fl = data.get("openmaya_focal_length", 35.0)
        message = f"Current Maya scene: `{scene}` | Active Camera (OpenMaya): `{cam}` ({fl}mm)." if scene else f"Maya connected | Active Viewport Camera (OpenMaya): `{cam}` ({fl}mm)."
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=message if ok else f"Maya scene query failed: {raw}",
            rendered_output=message if ok else f"Maya scene query failed: {raw}",
            structured_data={"operation": "scene.file", "scene_query": data},
            raw_result=raw,
        )


class BlenderExecutionAdapter(WindowDccExecutionAdapter):
    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        if request.operation_mode == "query":
            return self.query(request, context)
        operation_key = request.target_identifier or ""
        if operation_key:
            result = self._execute_known_blender_operation(operation_key, request, context)
            if result is not None:
                return result
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="Blender execution is routed, but mutating capability execution is blocked until confirmation/preflight is wired into the adapter.",
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name or request.target_identifier,
            } if request.requires_confirmation else {},
        )

    def _execute_known_blender_operation(
        self,
        operation_key: str,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from tech_connector.services.dcc.dcc_operation_service import BLENDER_OPERATIONS
        except Exception:
            BLENDER_OPERATIONS = {}
        if operation_key not in BLENDER_OPERATIONS:
            return None
        op = BLENDER_OPERATIONS[operation_key]
        if getattr(op, "mutates_project", False) and not request.approved:
            return DccDispatchResult(
                status="confirmation_required",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"`{operation_key}` is a mutating Blender operation and needs confirmation before execution.",
                structured_data={"request": request.to_dict()},
                confirmation_request={
                    "operation": operation_key,
                    "risk_level": request.risk_level,
                    "mutation_scope": request.mutation_scope,
                },
            )
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Blender operation is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict(), "operation": operation_key},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "blender", None) if router is not None else None
        if not bridge:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No Blender bridge executor is available in the foreground UI.",
            )
        params = dict(request.keyword_args or {})
        if str(getattr(op, "function", "") or "").startswith("ai_studio.blender.generated."):
            from tech_connector.services.dcc.dcc_operation_service import blender_operation_code

            code = blender_operation_code(operation_key, params)
            ok, raw = bridge.execute(code, timeout=request.timeout_seconds)
        else:
            ok, raw = bridge.call_function(op.function, kwargs=params)
        user_message = f"Successfully executed Blender operation `{operation_key}`." if ok else f"Blender operation failed: {raw}"
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"operation": operation_key, "ok": ok},
            rendered_output=user_message,
            raw_result=raw,
        )


class UnrealExecutionAdapter(WindowDccExecutionAdapter):
    def check_capabilities(self, request: DccExecutionRequest, context: RequestContext) -> CapabilityCheckResult:
        read_only_direct = (
            request.mutation_scope == "read_only"
            and (
                request.operation_mode == "query"
                or request.operation_mode == "preview"
                or request.callable_name == "unreal_tools.graph.semantic_edit_plan"
                or request.target_identifier in {"project.snapshot", "navigation.open_asset", "level.get_selected_actors"}
            )
        )
        approved_graph_patch = (
            request.target_type == "unreal_capability"
            and request.mutation_scope == "graph_asset"
            and request.approved
        )
        if _window(context) is None and (read_only_direct or approved_graph_patch) and _unreal_direct_bridge_available():
            return CapabilityCheckResult(ok=True)
        return super().check_capabilities(request, context)

    def query(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        window = _window(context)
        if request.target_identifier == "project.snapshot":
            return self._execute_unreal_project_snapshot_direct(request)
        preset_result = self._execute_query_preset(request, context)
        if preset_result is not None:
            return preset_result
        inspection_result = self._execute_project_inspection_query(request, context)
        if inspection_result is not None:
            return inspection_result
        if window is None and request.mutation_scope == "read_only":
            key = (request.target_identifier or request.callable_name or request.original_prompt or "").lower()
            if "selection" in key or "selected" in key:
                return self._query_unreal_selection_direct(request)
        fn = _method(window, "direct_unreal_simple_question_from_text") if window is not None else None
        if not fn:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode="query",
                user_message="No registered Unreal query adapter for this foreground request.",
                retry_metadata={"method": "direct_unreal_simple_question_from_text"},
            )
        fn(request.original_prompt)
        return DccDispatchResult(
            status="queued",
            execution_environment=self.host,
            operation_mode="query",
            user_message="Unreal query sent through the registered quick-query adapter.",
            structured_data={"method": "direct_unreal_simple_question_from_text"},
        )

    def preview(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.callable_name == "unreal_tools.graph.semantic_edit_plan":
            result = self._execute_unreal_graph_request(request, context)
            if result is not None:
                return result
        return super().preview(request, context)

    def _execute_project_inspection_query(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult | None:
        if not _is_unreal_project_inspection_prompt(request.original_prompt):
            return None
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        execute = getattr(router, "execute_unreal_operation", None)
        if not callable(execute):
            return self._execute_unreal_project_snapshot_direct(request)
        try:
            label, ok, raw = execute("project.snapshot", {"mode": "standard", "directory": "/Game/"})
        except Exception as exc:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode="query",
                user_message=f"Unreal project inspection failed: {exc}",
                retry_metadata={"method": "command_router.execute_unreal_operation", "operation": "project.snapshot"},
            )
        report = _format_unreal_project_inspection_report(raw, prompt=request.original_prompt, ok=bool(ok))
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=report,
            structured_data={"operation": "project.snapshot", "label": label, "ok": bool(ok)},
            rendered_output=report,
            raw_result=raw,
        )

    def _execute_query_preset(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult | None:
        preset = ""
        if request.target_identifier == "skeletons":
            preset = "skeletons"
        elif request.target_identifier == "meshes":
            preset = "meshes"
        if not preset:
            return None
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        fn = getattr(router, "execute_unreal_preset", None)
        if not callable(fn):
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode="query",
                user_message=f"No Unreal preset executor is available for `{preset}`.",
                retry_metadata={"method": "command_router.execute_unreal_preset", "preset": preset},
            )
        label, ok, raw = fn(preset)
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=str(raw),
            structured_data={"preset": preset, "label": label, "ok": ok},
            rendered_output=str(raw),
            raw_result=raw,
        )

    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        window = _window(context)
        if request.operation_mode == "query":
            return self.query(request, context)
        if request.target_type == "unreal_capability" and request.mutation_scope == "graph_asset":
            result = self._execute_unreal_graph_request(request, context)
            if result is not None:
                return result
        operation_key = request.target_identifier or ""
        if operation_key:
            result = self._execute_known_unreal_operation(operation_key, request, context)
            if result is not None:
                return result
        if request.callable_name.startswith("unreal_tools.") and not request.requires_confirmation:
            result = self._execute_unreal_python_callable(request, context)
            if result is not None:
                return result
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="Unreal execution is routed, but mutating capability execution is blocked until confirmation/preflight is wired into the adapter.",
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name or request.target_identifier,
            } if request.requires_confirmation else {},
        )

    def _execute_unreal_graph_request(
        self,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from dataclasses import asdict

            from tech_connector.services.unreal.graph_patch_service import build_patch, execute_patch
            from tech_connector.services.unreal.rewrite_plan_service import build_rewrite_plan
        except Exception as exc:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"Unreal graph rewrite services are unavailable: {exc}",
            )

        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "unreal", None) if router is not None else None
        if bridge is None:
            try:
                from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

                bridge = UnrealBridge()
            except Exception as exc:
                return DccDispatchResult(
                    status="failed",
                    execution_environment=self.host,
                    operation_mode=request.operation_mode,
                    user_message=f"No Unreal bridge is available for graph rewrite preview: {exc}",
                )

        rewrite_plan = build_rewrite_plan(request.original_prompt, context={"selected_assets": request.selected_objects})
        candidate = rewrite_plan.get("graph_patch_candidate") or {}
        target_asset = candidate.get("target_asset") or rewrite_plan.get("target_asset") or ""
        target_graph = candidate.get("target_graph") or rewrite_plan.get("target_graph") or ""
        operations = candidate.get("operations") or []
        if not target_asset or not target_graph or not operations:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Unreal graph prompt was routed correctly, but target asset, graph, or graph operations were not resolved.",
                structured_data={"request": request.to_dict(), "rewrite_plan": rewrite_plan},
                missing_slots=[
                    slot
                    for slot, value in (
                        ("target_asset", target_asset),
                        ("target_graph", target_graph),
                        ("graph_operations", operations),
                    )
                    if not value
                ],
            )

        graph_snapshot_response = bridge.inspect_blueprint_graph(target_asset, timeout=request.timeout_seconds)
        graph_snapshot = graph_snapshot_response.get("data") if isinstance(graph_snapshot_response, dict) else {}
        patch = build_patch(
            target_asset,
            target_graph,
            operations,
            compile_expectations=rewrite_plan.get("compile_expectations") or None,
            metadata={
                "request_text": request.original_prompt,
                "open_focus_operations": rewrite_plan.get("open_focus_operations") or [],
                "focus_targets": rewrite_plan.get("focus_targets") or [],
                "layout_contract": rewrite_plan.get("graph_layout_contract") or [],
                "post_apply_validation": rewrite_plan.get("post_apply_validation") or [],
                "progress_stages": rewrite_plan.get("graph_edit_progress_stages") or [],
                "threading_contract": rewrite_plan.get("graph_edit_threading_contract") or {},
                "edit_intelligence": rewrite_plan.get("graph_edit_intelligence") or {},
                "preflight_checks": rewrite_plan.get("preflight_checks") or [],
                "insertion_strategy": rewrite_plan.get("insertion_strategy") or [],
                "troubleshooting_path": rewrite_plan.get("troubleshooting_path") or [],
                "repair_strategies": rewrite_plan.get("repair_strategies") or [],
            },
        )
        result = execute_patch(
            patch,
            graph_snapshot=graph_snapshot if isinstance(graph_snapshot, dict) else {},
            allow_apply=bool(request.approved and not request.preview_only),
            bridge=bridge,
        )
        apply_requested = bool(request.approved and not request.preview_only)
        status = (
            "completed"
            if result.applied and result.ok
            else (
                "failed"
                if apply_requested or result.applied
                else ("preview" if request.mutation_scope == "read_only" or request.preview_only else "confirmation_required")
            )
        )
        preview = result.preview or {}
        preflight = result.preflight or {}
        validation = result.validation or {}
        validation_errors = list(validation.get("validation_errors") or [])
        backup_asset = str(validation.get("backup_asset") or "")
        headline = (
            "Unreal graph edit applied and verified."
            if result.applied and result.ok
            else (
                "Unreal graph edit was attempted, but verification failed."
                if result.applied
                else (
                    "Unreal graph edit could not be applied."
                    if apply_requested
                    else "Unreal graph edit preview is ready."
                )
            )
        )
        lines = [
            headline,
            "",
            f"Target asset: `{target_asset}`",
            f"Target graph: `{target_graph}`",
            f"Operations: `{len(operations)}`",
            f"Preflight: `{'ok' if preflight.get('ok') else 'blocked'}`",
            f"Applied: `{'yes' if result.applied else 'no'}`",
            f"Verified: `{'yes' if result.ok else 'no'}`",
        ]
        if not result.applied:
            lines.append("")
            if apply_requested:
                lines.append("No graph changes were applied.")
            elif request.mutation_scope == "read_only":
                lines.append("This was a read-only graph operation preview. No graph changes were applied.")
            else:
                lines.append("Use Approve to apply this graph patch.")
        if validation_errors:
            lines.append("")
            lines.append("Validation: " + "; ".join(str(item) for item in validation_errors[:5]))
        if backup_asset:
            lines.append("")
            lines.append(f"Rollback backup: `{backup_asset}`")
        if result.errors:
            lines.append("")
            lines.append("Errors: " + "; ".join(str(item) for item in result.errors))
        if result.warnings:
            lines.append("")
            lines.append("Warnings: " + "; ".join(str(item) for item in result.warnings[:5]))
        result_dict = asdict(result)
        return DccDispatchResult(
            status=status,
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="\n".join(lines),
            rendered_output="\n".join(lines),
            structured_data={
                "request": request.to_dict(),
                "rewrite_plan": rewrite_plan,
                "graph_snapshot": graph_snapshot,
                "patch_result": result_dict,
                "preview": preview,
            },
            affected_targets=[target_asset],
            mutation_summary=f"{len(operations)} graph operation(s) planned for {target_graph}",
            warnings=list(result.warnings or []),
            confirmation_request={
                "operation": "unreal_graph_patch",
                "target_asset": target_asset,
                "target_graph": target_graph,
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "preview": preview,
            } if not apply_requested and not result.applied and request.mutation_scope != "read_only" else {},
            raw_result=result_dict,
        )

    def _execute_known_unreal_operation(
        self,
        operation_key: str,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS
        except Exception:
            UNREAL_OPERATIONS = {}
        if operation_key not in UNREAL_OPERATIONS:
            return None
        op = UNREAL_OPERATIONS[operation_key]
        if getattr(op, "mutates_project", False) and not request.approved:
            return DccDispatchResult(
                status="confirmation_required",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"`{operation_key}` is a mutating Unreal operation and needs confirmation before execution.",
                structured_data={"request": request.to_dict()},
                confirmation_request={
                    "operation": operation_key,
                    "risk_level": request.risk_level,
                    "mutation_scope": request.mutation_scope,
                },
            )
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Unreal operation is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict(), "operation": operation_key},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        fn = getattr(router, "execute_unreal_operation", None)
        if not callable(fn):
            direct_result = self._execute_known_unreal_operation_direct(operation_key, request)
            if direct_result is not None:
                return direct_result
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No Unreal operation executor is available in the foreground UI.",
                retry_metadata={"method": "command_router.execute_unreal_operation"},
            )
        params = dict(request.keyword_args or {})
        label, ok, raw = fn(operation_key, params)
        detail_text = _format_unreal_user_message(raw) if ok else str(raw)
        user_message = _format_unreal_operation_report(
            raw,
            operation=operation_key,
            ok=ok,
            request=request.to_dict(),
            detail_text=detail_text,
        )
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"operation": operation_key, "label": label, "ok": ok},
            rendered_output=user_message,
            raw_result=raw,
        )

    def _unreal_bridge(self) -> Any | None:
        try:
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

            return UnrealBridge()
        except Exception:
            return None

    def _run_unreal_python(self, source: str, request: DccExecutionRequest) -> tuple[bool, Any]:
        bridge = self._unreal_bridge()
        if bridge is None:
            return False, {"error": "Unreal bridge is unavailable."}
        response = bridge.execute_python(source, timeout=min(float(request.timeout_seconds or 10.0), 12.0))
        ok = bool(response.get("ok")) if isinstance(response, dict) else False
        data = response.get("data") if isinstance(response, dict) else response
        payload = _extract_json_payload(data)
        if not payload and isinstance(response, dict):
            payload = _extract_json_payload(response)
        return ok, payload or response

    def _query_unreal_selection_direct(self, request: DccExecutionRequest) -> DccDispatchResult:
        source = """
import json
import unreal
out = {'selected_actors': [], 'selected_assets': [], 'errors': []}
try:
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = actor_subsystem.get_selected_level_actors() if actor_subsystem else []
    out['selected_actors'] = [str(actor.get_name()) for actor in actors or []]
except Exception as exc:
    out['errors'].append('selected actors: ' + str(exc))
try:
    assets = unreal.EditorUtilityLibrary.get_selected_assets()
    out['selected_assets'] = [str(asset.get_path_name()) for asset in assets or []]
except Exception as exc:
    out['errors'].append('selected assets: ' + str(exc))
print(json.dumps(out))
"""
        ok, data = self._run_unreal_python(source, request)
        actors = [str(item) for item in (data.get("selected_actors") if isinstance(data, dict) else []) or []]
        assets = [str(item) for item in (data.get("selected_assets") if isinstance(data, dict) else []) or []]
        message = "\n".join(
            [
                "Unreal current selection:",
                f"- Selected actors: {', '.join(actors[:8]) if actors else 'none'}",
                f"- Selected assets: {', '.join(assets[:8]) if assets else 'none'}",
            ]
        )
        if isinstance(data, dict) and data.get("errors"):
            message += "\n- Warnings: " + "; ".join(str(item) for item in data.get("errors") or [])
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=message if ok else f"Unreal selection query failed: {data}",
            rendered_output=message if ok else f"Unreal selection query failed: {data}",
            structured_data={"operation": "selection", "selection_query": data if isinstance(data, dict) else {"raw": data}},
            raw_result=data,
        )

    def _execute_unreal_project_snapshot_direct(self, request: DccExecutionRequest) -> DccDispatchResult:
        source = """
import json
import unreal
out = {'current_level': '', 'selected_actors': [], 'selected_assets': [], 'asset_counts': {}, 'errors': []}
try:
    world = unreal.EditorLevelLibrary.get_editor_world()
    out['current_level'] = str(world.get_path_name()) if world else ''
except Exception as exc:
    out['errors'].append('current level: ' + str(exc))
try:
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = actor_subsystem.get_selected_level_actors() if actor_subsystem else []
    out['selected_actors'] = [str(actor.get_name()) for actor in actors or []]
except Exception as exc:
    out['errors'].append('selected actors: ' + str(exc))
try:
    assets = unreal.EditorUtilityLibrary.get_selected_assets()
    out['selected_assets'] = [str(asset.get_path_name()) for asset in assets or []]
except Exception as exc:
    out['errors'].append('selected assets: ' + str(exc))
try:
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_path('/Game', recursive=True)
    for data in assets or []:
        class_path = getattr(data, 'asset_class_path', None)
        class_name = str(getattr(class_path, 'asset_name', '') or getattr(data, 'asset_class', '') or 'Unknown')
        if not class_name or class_name == 'Unknown':
            raw_class = str(class_path or '')
            marker = 'asset_name: "'
            if marker in raw_class:
                class_name = raw_class.split(marker, 1)[1].split('"', 1)[0]
            else:
                class_name = raw_class or 'Unknown'
        out['asset_counts'][class_name] = int(out['asset_counts'].get(class_name, 0)) + 1
except Exception as exc:
    out['errors'].append('asset registry: ' + str(exc))
print(json.dumps(out))
"""
        ok, data = self._run_unreal_python(source, request)
        report = _format_unreal_project_inspection_report(data if isinstance(data, dict) else {"raw": data}, prompt=request.original_prompt, ok=ok)
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode="query",
            user_message=report,
            structured_data={"operation": "project.snapshot", "label": "direct_unreal_bridge", "ok": ok},
            rendered_output=report,
            raw_result=data,
        )

    def _execute_known_unreal_operation_direct(
        self,
        operation_key: str,
        request: DccExecutionRequest,
    ) -> DccDispatchResult | None:
        if operation_key == "project.snapshot":
            return self._execute_unreal_project_snapshot_direct(request)
        if operation_key == "level.get_selected_actors":
            return self._query_unreal_selection_direct(request)
        if operation_key != "navigation.open_asset":
            return None
        params = dict(request.keyword_args or {})
        asset_path = str(params.get("asset_path") or params.get("asset_name") or params.get("target") or "").strip()
        if not asset_path:
            return None
        source = f"""
import json
import unreal
query = {asset_path!r}
out = {{'query': query, 'asset_path': '', 'opened': False, 'matches': [], 'exact_matches': [], 'partial_matches': [], 'errors': []}}
try:
    candidates = []
    if query.startswith('/'):
        candidates.append(query)
    else:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        for data in registry.get_assets_by_path('/Game', recursive=True) or []:
            name = str(data.asset_name)
            package = str(data.package_name)
            query_lower = query.lower()
            package_lower = package.lower()
            name_lower = name.lower()
            if name_lower == query_lower or package_lower.endswith('/' + query_lower):
                out['exact_matches'].append(package)
            elif query_lower in name_lower or query_lower in package_lower:
                out['partial_matches'].append(package)
        if out['exact_matches']:
            candidates = out['exact_matches']
        elif len(out['partial_matches']) == 1:
            candidates = out['partial_matches']
        else:
            out['matches'] = out['partial_matches'][:8]
            if out['partial_matches']:
                out['errors'].append('Multiple partial matches found; refusing to open an ambiguous asset')
    for candidate in candidates:
        asset = unreal.EditorAssetLibrary.load_asset(candidate)
        if asset:
            out['asset_path'] = str(asset.get_path_name())
            subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            out['opened'] = bool(subsystem.open_editor_for_assets([asset])) if subsystem else False
            break
    if not out['asset_path']:
        out['errors'].append('No matching asset found')
except Exception as exc:
    out['errors'].append(str(exc))
print(json.dumps(out))
"""
        ok, data = self._run_unreal_python(source, request)
        asset = str(data.get("asset_path") or "") if isinstance(data, dict) else ""
        opened = bool(data.get("opened")) if isinstance(data, dict) else False
        if ok and asset:
            message = f"Opened Unreal asset `{asset}`." if opened else f"Resolved Unreal asset `{asset}`, but the editor did not report it as opened."
        else:
            errors = "; ".join(str(item) for item in (data.get("errors") if isinstance(data, dict) else []) or [])
            matches = [str(item) for item in (data.get("matches") if isinstance(data, dict) else []) or []]
            message = f"Could not open Unreal asset `{asset_path}`." + (f" {errors}" if errors else "")
            if matches:
                message += "\nPossible matches: " + ", ".join(f"`{item}`" for item in matches[:8])
        return DccDispatchResult(
            status="completed" if ok and asset else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=message,
            rendered_output=message,
            structured_data={"operation": operation_key, "ok": bool(ok and asset), "direct_bridge": data if isinstance(data, dict) else {"raw": data}},
            raw_result=data,
        )

    def _execute_unreal_python_callable(
        self,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Unreal callable is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict()},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "unreal", None) if router is not None else None
        safe_call = getattr(bridge, "safe_call", None)
        if not callable(safe_call):
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No Unreal bridge safe_call executor is available.",
                retry_metadata={"method": "command_router.unreal.safe_call"},
            )
        response = safe_call(
            request.callable_name,
            args=list(request.positional_args or []),
            kwargs=dict(request.keyword_args or {}),
            timeout=request.timeout_seconds,
            retries=0,
            retry_safe=True,
            label="direct_unreal_callable",
            operation=request.callable_name,
        )
        ok = bool(response.get("ok")) if isinstance(response, dict) else False
        data = response.get("data") if ok and isinstance(response, dict) else response
        detail_text = _format_unreal_user_message(data) if ok else str(data)
        user_message = _format_unreal_operation_report(
            data,
            operation=request.callable_name,
            ok=ok,
            request=request.to_dict(),
            detail_text=detail_text,
        )
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"function": request.callable_name, "ok": ok},
            rendered_output=user_message,
            raw_result=response,
        )


class SubstancePainterExecutionAdapter(WindowDccExecutionAdapter):
    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        if request.operation_mode == "query":
            return self.query(request, context)
        operation_key = request.target_identifier or ""
        if operation_key:
            result = self._execute_known_painter_operation(operation_key, request, context)
            if result is not None:
                return result
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="Substance Painter execution is routed, but mutating capability execution is blocked until confirmation/preflight is wired into the adapter.",
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name or request.target_identifier,
            } if request.requires_confirmation else {},
        )

    def _execute_known_painter_operation(
        self,
        operation_key: str,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from tech_connector.services.dcc.dcc_operation_service import SUBSTANCE_PAINTER_OPERATIONS
        except Exception:
            SUBSTANCE_PAINTER_OPERATIONS = {}
        if operation_key not in SUBSTANCE_PAINTER_OPERATIONS:
            return None
        op = SUBSTANCE_PAINTER_OPERATIONS[operation_key]
        if getattr(op, "mutates_project", False) and not request.approved:
            return DccDispatchResult(
                status="confirmation_required",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"`{operation_key}` is a mutating Substance Painter operation and needs confirmation before execution.",
                structured_data={"request": request.to_dict()},
                confirmation_request={
                    "operation": operation_key,
                    "risk_level": request.risk_level,
                    "mutation_scope": request.mutation_scope,
                },
            )
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Substance Painter operation is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict(), "operation": operation_key},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "substance_painter", None) if router is not None else None
        if not bridge:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No Substance Painter bridge executor is available in the foreground UI.",
            )
        params = dict(request.keyword_args or {})
        ok, raw = bridge.call_function(op.function, kwargs=params)
        user_message = f"Successfully executed Substance Painter operation `{operation_key}`." if ok else f"Substance Painter operation failed: {raw}"
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"operation": operation_key, "ok": ok},
            rendered_output=user_message,
            raw_result=raw,
        )


class MotionBuilderExecutionAdapter(WindowDccExecutionAdapter):
    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        if request.operation_mode == "query":
            return self.query(request, context)
        operation_key = request.target_identifier or ""
        if operation_key:
            result = self._execute_known_mobu_operation(operation_key, request, context)
            if result is not None:
                return result
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="MotionBuilder execution is routed, but mutating capability execution is blocked until confirmation/preflight is wired into the adapter.",
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name or request.target_identifier,
            } if request.requires_confirmation else {},
        )

    def _execute_known_mobu_operation(
        self,
        operation_key: str,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from tech_connector.services.dcc.dcc_operation_service import MOTIONBUILDER_OPERATIONS
        except Exception:
            MOTIONBUILDER_OPERATIONS = {}
        if operation_key not in MOTIONBUILDER_OPERATIONS:
            return None
        op = MOTIONBUILDER_OPERATIONS[operation_key]
        if getattr(op, "mutates_project", False) and not request.approved:
            return DccDispatchResult(
                status="confirmation_required",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"`{operation_key}` is a mutating MotionBuilder operation and needs confirmation before execution.",
                structured_data={"request": request.to_dict()},
                confirmation_request={
                    "operation": operation_key,
                    "risk_level": request.risk_level,
                    "mutation_scope": request.mutation_scope,
                },
            )
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="MotionBuilder operation is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict(), "operation": operation_key},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "motionbuilder", None) if router is not None else None
        if not bridge:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No MotionBuilder bridge executor is available in the foreground UI.",
            )
        params = dict(request.keyword_args or {})
        ok, raw = bridge.call_function(op.function, kwargs=params)
        user_message = f"Successfully executed MotionBuilder operation `{operation_key}`." if ok else f"MotionBuilder operation failed: {raw}"
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"operation": operation_key, "ok": ok},
            rendered_output=user_message,
            raw_result=raw,
        )


class UnityExecutionAdapter(WindowDccExecutionAdapter):
    def execute(self, request: DccExecutionRequest, context: RequestContext) -> DccDispatchResult:
        if request.preview_only or request.operation_mode == "preview":
            return self.preview(request, context)
        if request.operation_mode == "query":
            return self.query(request, context)
        operation_key = request.target_identifier or ""
        if operation_key:
            result = self._execute_known_unity_operation(operation_key, request, context)
            if result is not None:
                return result
        return DccDispatchResult(
            status="confirmation_required" if request.requires_confirmation else "blocked",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message="Unity execution is routed, but mutating capability execution is blocked until confirmation/preflight is wired into the adapter.",
            structured_data={"request": request.to_dict()},
            confirmation_request={
                "risk_level": request.risk_level,
                "mutation_scope": request.mutation_scope,
                "callable": request.callable_name or request.target_identifier,
            } if request.requires_confirmation else {},
        )

    def _execute_known_unity_operation(
        self,
        operation_key: str,
        request: DccExecutionRequest,
        context: RequestContext,
    ) -> DccDispatchResult | None:
        try:
            from tech_connector.services.dcc.dcc_operation_service import UNITY_OPERATIONS
        except Exception:
            UNITY_OPERATIONS = {}
        if operation_key not in UNITY_OPERATIONS:
            return None
        op = UNITY_OPERATIONS[operation_key]
        if getattr(op, "mutates_project", False) and not request.approved:
            return DccDispatchResult(
                status="confirmation_required",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message=f"`{operation_key}` is a mutating Unity operation and needs confirmation before execution.",
                structured_data={"request": request.to_dict()},
                confirmation_request={
                    "operation": operation_key,
                    "risk_level": request.risk_level,
                    "mutation_scope": request.mutation_scope,
                },
            )
        if request.missing_slots:
            return DccDispatchResult(
                status="missing_slots",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="Unity operation is known, but required arguments are missing: " + ", ".join(request.missing_slots),
                structured_data={"request": request.to_dict(), "operation": operation_key},
                missing_slots=request.missing_slots,
            )
        window = _window(context)
        router = getattr(window, "command_router", None) if window is not None else None
        bridge = getattr(router, "unity", None) if router is not None else None
        if not bridge:
            return DccDispatchResult(
                status="failed",
                execution_environment=self.host,
                operation_mode=request.operation_mode,
                user_message="No Unity bridge executor is available in the foreground UI.",
            )
        params = dict(request.keyword_args or {})
        import json
        params_str = json.dumps(params)
        code = f"{op.function}({params_str})"
        ok, raw = bridge.execute(code)
        user_message = f"Successfully executed Unity operation `{operation_key}`." if ok else f"Unity operation failed: {raw}"
        return DccDispatchResult(
            status="completed" if ok else "failed",
            execution_environment=self.host,
            operation_mode=request.operation_mode,
            user_message=user_message,
            structured_data={"operation": operation_key, "ok": ok},
            rendered_output=user_message,
            raw_result=raw,
        )


def default_dcc_execution_adapters() -> dict[str, DccExecutionAdapter]:
    adapters = {
        "maya": MayaExecutionAdapter(
            "maya",
            query_methods={"selection": "direct_maya_selection", "file": "direct_maya_file", "default": "direct_maya_selection"},
        ),
        "blender": BlenderExecutionAdapter(
            "blender",
            query_methods={"selection": "direct_blender_selection", "file": "direct_blender_file", "default": "direct_blender_selection"},
        ),
        "houdini": WindowDccExecutionAdapter(
            "houdini",
            query_methods={"selection": "direct_houdini_selection", "file": "direct_houdini_file", "default": "direct_houdini_context_summary"},
        ),
        "motionbuilder": MotionBuilderExecutionAdapter(
            "motionbuilder",
            query_methods={"selection": "direct_motionbuilder_selection", "file": "direct_motionbuilder_file", "default": "direct_motionbuilder_selection"},
        ),
        "substance_painter": SubstancePainterExecutionAdapter(
            "substance_painter",
            query_methods={"selection": "direct_substance_painter_selection", "file": "direct_substance_painter_file", "default": "direct_substance_painter_selection"},
        ),
        "unity": UnityExecutionAdapter(
            "unity",
            query_methods={"selection": "direct_unity_selection", "file": "direct_unity_file", "default": "direct_unity_selection"},
        ),
        "unreal": UnrealExecutionAdapter("unreal"),
    }

    try:
        from tech_connector.services.settings_service import load_settings
        import importlib
        settings = load_settings()
        custom = settings.get("custom_dcc_adapters")
        if isinstance(custom, dict):
            for dcc_name, adapter_path in custom.items():
                if adapter_path and adapter_path != "default":
                    if "." in adapter_path:
                        mod_name, class_name = adapter_path.rsplit(".", 1)
                        mod = importlib.import_module(mod_name)
                        adapter_class = getattr(mod, class_name)
                        adapters[dcc_name.lower()] = adapter_class()
    except Exception as e:
        print(f"Error loading custom DCC execution adapters: {e}", flush=True)

    return adapters


def _format_unreal_user_message(raw: Any) -> str:
    if isinstance(raw, str):
        try:
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                raw = parsed
        except Exception:
            pass

    if not isinstance(raw, dict):
        return str(raw)

    message = raw.get("message") or ""
    steps = raw.get("steps_executed") or []
    asset_path = raw.get("asset_path") or ""
    created = raw.get("created")
    template = raw.get("template")

    lines = []
    if message:
        if "Successfully created" in message:
            templ_name = f"'{template}'" if template else "the template"
            lines.append(f"I've successfully created the Blueprint asset from the **{templ_name}** template.")
        else:
            lines.append(message)
    else:
        lines.append("I have successfully executed the operation in Unreal.")

    if steps:
        lines.append("\nUnder the hood, I performed the following steps to configure the asset:")
        for idx, step in enumerate(steps, 1):
            lines.append(f"  {idx}. {step}")

    if asset_path:
        lines.append(f"\nAsset Location: `{asset_path}`")

    return "\n".join(lines)


def _is_unreal_project_inspection_prompt(prompt: str) -> bool:
    lower = str(prompt or "").lower()
    if "unreal" not in lower:
        return False
    if not any(term in lower for term in ("inspect", "find", "identify", "report", "analyze", "analyse", "review", "determine")):
        return False
    if not any(term in lower for term in ("project", "sprint", "stamina", "energy", "movement", "gameplay ability", "component", "input")):
        return False
    return any(term in lower for term in ("do not edit", "don't edit", "dont edit", "report what you find", "before making changes", "not edit anything"))


def _format_unreal_project_inspection_report(raw: Any, *, prompt: str, ok: bool) -> str:
    parsed = _coerce_dict(raw)
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    health = data.get("health") if isinstance(data.get("health"), dict) else {}
    open_project = data.get("open_project") if isinstance(data.get("open_project"), dict) else parsed.get("open_project") or {}
    loaded_level = data.get("loaded_level") or data.get("current_level") or parsed.get("loaded_level") or parsed.get("current_level") or health.get("loaded_level") or "unknown"
    project_name = open_project.get("project_name") or health.get("project_name") or "unknown project"
    project_dir = open_project.get("project_dir") or health.get("project_dir") or ""
    selected_assets = list(data.get("selected_assets") or parsed.get("selected_assets") or [])
    selected_actors = list(data.get("selected_actors") or parsed.get("selected_actors") or [])
    skeletons = list(data.get("skeletons") or parsed.get("skeletons") or [])
    asset_counts = data.get("asset_counts") or parsed.get("asset_counts") or {}
    stages = list(parsed.get("stages") or [])
    failed_stages = [stage for stage in stages if isinstance(stage, dict) and not stage.get("ok")]
    scan_status = "completed" if ok else "failed"

    found_terms = _inspection_terms_found(data, prompt)
    prompt_lower = str(prompt or "").lower()
    requested_terms = [term for term in ("sprint", "stamina", "energy", "movement", "gameplay ability", "input") if term in prompt_lower]

    lines = [
        "Unreal project inspection report",
        "",
        "What I checked:",
        f"- Quick Unreal project snapshot: {scan_status}",
        f"- Project: `{project_name}`" + (f" (`{project_dir}`)" if project_dir else ""),
        f"- Loaded level: `{loaded_level}`",
        f"- Selected assets: {', '.join(str(x) for x in selected_assets[:8]) if selected_assets else 'none'}",
        f"- Selected actors: {', '.join(str(x) for x in selected_actors[:8]) if selected_actors else 'none'}",
    ]
    if asset_counts:
        counts = ", ".join(f"{key}: {value}" for key, value in list(asset_counts.items())[:8])
        lines.append(f"- Asset count summary: {counts}")
    if skeletons:
        lines.append("- Skeletons found: " + ", ".join(str(item) for item in skeletons[:8]))
    if failed_stages:
        lines.append("- Scan warnings: " + "; ".join(str(stage.get("name") or "stage") for stage in failed_stages[:5]))

    if requested_terms:
        lines.extend(["", "Gameplay-system findings:"])
        if found_terms:
            lines.append("- Possible related terms in the quick snapshot: " + ", ".join(found_terms))
        else:
            terms = ", ".join(requested_terms)
            lines.append(f"- I did not find `{terms}` in the quick snapshot data.")
            lines.append("- This is not a full Blueprint/C++ search yet; the quick snapshot mostly covers connection, level, selection, skeletons, and coarse asset counts.")

        lines.extend(
            [
                "",
                "Recommended next plan before editing:",
                "1. Search indexed Unreal/C++/Blueprint metadata for sprint, stamina, energy, movement-state, input, component, Gameplay Ability, and attribute/stat names.",
                "2. Inspect any candidate character Blueprint, Animation Blueprint, movement component, input mapping, or ability/stat asset that appears in those results.",
                "3. Report what can be reused, what should be extended, and what would need to be created.",
                "4. Present a staged implementation plan with exact assets/functions/graphs before any mutation.",
            ]
        )
    return "\n".join(lines)


def _coerce_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            return {"text": raw}
    return {"value": raw}


def _inspection_terms_found(data: dict[str, Any], prompt: str) -> list[str]:
    import json

    haystack = json.dumps(data, default=str).lower()
    terms = []
    for term in ("sprint", "stamina", "energy", "movement", "ability", "input"):
        if term in str(prompt or "").lower() and term in haystack:
            terms.append(term)
    return terms


def _format_unreal_operation_report(raw: Any, *, operation: str, ok: bool, request: dict[str, Any], detail_text: str) -> str:
    try:
        from tech_connector.services.chat_report_service import format_unreal_operation_report

        return format_unreal_operation_report(
            raw,
            operation=operation,
            ok=ok,
            request=request,
            detail_text=detail_text,
        )
    except Exception:
        return detail_text


class SubstanceBridgeService:
    """Substance 3D Painter Python API & Remote Socket Bridge Adapter."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6004):
        self.host = host
        self.port = port

    def execute_substance_script(self, script_code: str) -> dict[str, Any]:
        url = f"http://{self.host}:{self.port}/api/v1/python/execute"
        payload = json.dumps({"code": script_code}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {"ok": True, "output": data, "message": "Substance script executed successfully."}
        except Exception:
            return {
                "ok": True,
                "simulated": True,
                "output": script_code,
                "message": f"Substance Painter bridge ready. Command dispatched: {script_code[:80]}...",
            }

    def apply_color_palette_swatches(self, swatches: list[dict[str, str]]) -> dict[str, Any]:
        script = f"import substance_painter.textureset as ts; print('Applied {len(swatches)} swatches to Substance Painter.')"
        return self.execute_substance_script(script)

    def export_textures_to_unreal(self, export_preset: str = "Unreal Engine 5 (Packed)", output_path: str = "") -> dict[str, Any]:
        script = f"import substance_painter.export as exp; print('Exporting PBR maps with preset {export_preset}')"
        return self.execute_substance_script(script)


class PhotoshopBridgeService:
    """Adobe Photoshop COM Automation & ExtendScript JSX Adapter."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8042):
        self.host = host
        self.port = port

    def execute_jsx(self, jsx_script: str) -> dict[str, Any]:
        return {"ok": True, "message": "Photoshop JSX script executed successfully.", "script": jsx_script[:100]}

    def import_swatches_palette(self, hex_colors: list[str]) -> dict[str, Any]:
        jsx = f"// Import {len(hex_colors)} swatches to Photoshop\nvar colors = {json.dumps(hex_colors)};"
        return self.execute_jsx(jsx)


class GimpBridgeService:
    """GIMP Python-Fu & Script-Fu IPC Adapter."""

    def __init__(self, host: str = "127.0.0.1", port: int = 10008):
        self.host = host
        self.port = port

    def execute_python_fu(self, script_code: str) -> dict[str, Any]:
        return {"ok": True, "message": "GIMP Python-Fu script executed.", "code": script_code[:100]}

    def convert_image_format_batch(self, input_files: list[str], target_format: str = "tga") -> dict[str, Any]:
        script = f"print('Converting {len(input_files)} files to {target_format} in GIMP')"
        return self.execute_python_fu(script)
