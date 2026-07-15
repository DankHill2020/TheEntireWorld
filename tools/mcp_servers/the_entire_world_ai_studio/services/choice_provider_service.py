"""Generic choice providers for structured clarification controls.

The UI asks for choices by provider id and slot metadata. Providers own lookup,
ranking, stale state, and stable typed values so widgets never translate labels
into project or host objects.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


@dataclass
class RecoveryOption:
    action_id: str
    label: str
    description: str = ""
    safe: bool = True
    requires_confirmation: bool = False
    resumes_operation: bool = True
    resolves_capability: str = ""
    typed_request: dict[str, Any] = field(default_factory=dict)
    requires_refresh: bool = False
    requires_reconnect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChoiceProviderRequest:
    provider_id: str
    slot_name: str
    query: str | None = None
    page_token: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    continuation_id: str | None = None
    timeout_seconds: float = 5.0


@dataclass
class ChoiceItem:
    value: Any
    label: str
    description: str | None = None
    detail: str | None = None
    icon_key: str | None = None
    group: str | None = None
    search_terms: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    is_recommended: bool = False
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChoiceProviderResult:
    status: str
    choices: list[ChoiceItem] = field(default_factory=list)
    next_page_token: str | None = None
    is_stale: bool = False
    can_refresh: bool = True
    error: str | None = None
    recovery_options: list[RecoveryOption] = field(default_factory=list)
    provider_id: str = ""
    latency_ms: float = 0.0
    refresh_policy: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["choices"] = [choice.to_dict() for choice in self.choices]
        payload["recovery_options"] = [option.to_dict() for option in self.recovery_options]
        return payload


@dataclass
class ChoiceProviderJobSnapshot:
    job_id: str
    provider_id: str
    slot_name: str
    status: str
    created_at: float
    started_at: float = 0.0
    completed_at: float = 0.0
    cancelled: bool = False
    result: ChoiceProviderResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result"] = self.result.to_dict() if self.result else None
        return payload


class ChoiceProvider(Protocol):
    provider_id: str
    refresh_policy: str

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult: ...


class StaticChoiceProvider:
    provider_id = "static"
    refresh_policy = "never"

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult:
        values = list(request.filters.get("choices") or [])
        return _result(
            self.provider_id,
            [choice_item(value, group="Static") for value in values],
            refresh_policy=self.refresh_policy,
        )


class OperationMemoryChoiceProvider:
    provider_id = "operation.memory"
    refresh_policy = "manual"

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult:
        memory = request.context_snapshot.get("operation_memory") or {}
        choices: list[ChoiceItem] = []
        if isinstance(memory, dict):
            resolved = memory.get("resolved_slots") or {}
            if request.slot_name in resolved:
                choices.append(
                    choice_item(
                        resolved[request.slot_name],
                        group="Recent",
                        is_recommended=True,
                        confidence=0.95,
                        metadata={"source": "operation_memory", "updated_at": memory.get("updated_at")},
                    )
                )
            if request.slot_name == "execution_environment" and memory.get("selected_host"):
                choices.append(
                    choice_item(
                        memory.get("selected_host"),
                        group="Recent",
                        is_recommended=True,
                        confidence=0.95,
                        metadata={"source": "operation_memory", "updated_at": memory.get("updated_at")},
                    )
                )
        return _result(self.provider_id, _dedupe_choices(choices), refresh_policy=self.refresh_policy)


class ProjectFileChoiceProvider:
    provider_id = "project.files"
    refresh_policy = "index_or_project_change"

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult:
        roots = list(request.context_snapshot.get("project_roots") or [])
        query = (request.query or request.filters.get("query") or "").lower()
        suffixes = tuple(request.filters.get("suffixes") or ())
        limit = int(request.filters.get("limit") or 80)
        choices: list[ChoiceItem] = []
        for root in roots[:4]:
            base = Path(str(root))
            if not base.exists():
                continue
            try:
                for path in base.rglob("*"):
                    if len(choices) >= limit:
                        break
                    if not path.is_file():
                        continue
                    if suffixes and path.suffix.lower() not in suffixes:
                        continue
                    rel = str(path.relative_to(base))
                    if query and query not in rel.lower() and query not in path.name.lower():
                        continue
                    choices.append(
                        ChoiceItem(
                            value=str(path),
                            label=path.name,
                            detail=rel,
                            icon_key="file",
                            group="Project files",
                            search_terms=(path.name, rel),
                            metadata={"root": str(base), "source": "filesystem"},
                        )
                    )
            except Exception:
                continue
        return _result(self.provider_id, choices, refresh_policy=self.refresh_policy)


class ProjectSymbolChoiceProvider:
    provider_id = "project.symbol_search"
    refresh_policy = "index_change"

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult:
        query = str(request.query or request.filters.get("query") or request.slot_name or "")
        if not query:
            return _result(self.provider_id, [], status="empty", refresh_policy=self.refresh_policy)
        try:
            from knowledge.search import search_index_symbols

            rows = search_index_symbols(
                [query],
                limit=int(request.filters.get("limit") or 40),
                active_path=str(request.context_snapshot.get("active_file") or ""),
                scope=str(request.filters.get("scope") or "project"),
                project_roots=list(request.context_snapshot.get("project_roots") or []),
            )
        except Exception as exc:
            return ChoiceProviderResult(
                status="failed",
                provider_id=self.provider_id,
                error=str(exc),
                recovery_options=[RecoveryOption("rebuild_index", "Rebuild project index", requires_refresh=True)],
                refresh_policy=self.refresh_policy,
            )
        kinds = set(request.filters.get("symbol_kinds") or [])
        choices = []
        for row in rows:
            if kinds and str(row.get("kind") or "") not in kinds:
                continue
            label = str(row.get("qualname") or row.get("name") or "")
            choices.append(
                ChoiceItem(
                    value={"name": row.get("name"), "qualname": row.get("qualname"), "path": row.get("path"), "kind": row.get("kind")},
                    label=label or str(row.get("name") or "symbol"),
                    detail=str(row.get("path") or ""),
                    icon_key="symbol",
                    group=str(row.get("kind") or "Symbol"),
                    search_terms=(label, str(row.get("path") or "")),
                    metadata={"source": "project_index", "row": row},
                    confidence=float(row.get("score") or row.get("scope_score") or 0.0) / 100.0 if row.get("scope_score") else None,
                )
            )
        return _result(self.provider_id, choices, refresh_policy=self.refresh_policy)


class UnrealPresetChoiceProvider:
    refresh_policy = "host_reconnect_or_manual"

    def __init__(self, provider_id: str, preset: str, group: str):
        self.provider_id = provider_id
        self.preset = preset
        self.group = group

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult:
        window = request.context_snapshot.get("window")
        router = getattr(window, "command_router", None) if window is not None else None
        fn = getattr(router, "execute_unreal_preset", None)
        if not callable(fn):
            return ChoiceProviderResult(
                status="disconnected",
                provider_id=self.provider_id,
                error="Unreal preset executor is not connected.",
                recovery_options=[
                    RecoveryOption("reconnect_unreal", "Reconnect Unreal", resolves_capability="unreal_connection", requires_reconnect=True),
                    RecoveryOption("enter_manually", "Enter value manually", safe=True, resumes_operation=True),
                ],
                refresh_policy=self.refresh_policy,
            )
        try:
            _label, ok, raw = fn(self.preset)
        except Exception as exc:
            return ChoiceProviderResult(
                status="failed",
                provider_id=self.provider_id,
                error=str(exc),
                recovery_options=[RecoveryOption("retry", "Retry", requires_refresh=True)],
                refresh_policy=self.refresh_policy,
            )
        if not ok:
            return ChoiceProviderResult(
                status="failed",
                provider_id=self.provider_id,
                error=str(raw),
                recovery_options=[RecoveryOption("retry", "Retry", requires_refresh=True)],
                refresh_policy=self.refresh_policy,
            )
        values = _lines_from_raw(raw)
        return _result(
            self.provider_id,
            [choice_item(value, group=self.group, metadata={"source": "unreal", "preset": self.preset}) for value in values],
            refresh_policy=self.refresh_policy,
        )


class RegisteredUnrealOperationProvider:
    provider_id = "unreal.operations"
    refresh_policy = "manual"

    def choices(self, request: ChoiceProviderRequest) -> ChoiceProviderResult:
        try:
            from services.unreal.unreal_operation_service import UNREAL_OPERATIONS
        except Exception:
            UNREAL_OPERATIONS = {}
        query = str(request.query or "").lower()
        choices = []
        for key, op in sorted(UNREAL_OPERATIONS.items()):
            if query and query not in key.lower() and query not in getattr(op, "label", "").lower():
                continue
            choices.append(
                ChoiceItem(
                    value=key,
                    label=getattr(op, "label", key),
                    detail=getattr(op, "function", ""),
                    group="Unreal operations",
                    metadata={"operation_key": key, "mutates_project": getattr(op, "mutates_project", False)},
                )
            )
        return _result(self.provider_id, choices, refresh_policy=self.refresh_policy)


def default_choice_providers() -> dict[str, ChoiceProvider]:
    return {
        "static": StaticChoiceProvider(),
        "operation.memory": OperationMemoryChoiceProvider(),
        "project.files": ProjectFileChoiceProvider(),
        "project.symbol_search": ProjectSymbolChoiceProvider(),
        "project.callables": ProjectSymbolChoiceProvider(),
        "unreal.skeletons": UnrealPresetChoiceProvider("unreal.skeletons", "skeletons", "Unreal skeletons"),
        "unreal.meshes": UnrealPresetChoiceProvider("unreal.meshes", "meshes", "Unreal meshes"),
        "unreal.assets": UnrealPresetChoiceProvider("unreal.assets", "assets", "Unreal assets"),
        "unreal.operations": RegisteredUnrealOperationProvider(),
    }


CHOICE_PROVIDERS = default_choice_providers()


class ChoiceProviderJobManager:
    """Runs potentially slow choice providers away from the UI thread."""

    def __init__(self, providers: dict[str, ChoiceProvider] | None = None, max_workers: int = 4):
        self.providers = providers or CHOICE_PROVIDERS
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="choice-provider")
        self._jobs: dict[str, dict[str, Any]] = {}

    def start(self, request: ChoiceProviderRequest) -> ChoiceProviderJobSnapshot:
        job_id = str(uuid4())
        created_at = time.time()
        state: dict[str, Any] = {
            "job_id": job_id,
            "request": request,
            "status": "queued",
            "created_at": created_at,
            "started_at": 0.0,
            "completed_at": 0.0,
            "cancelled": False,
            "result": None,
            "error": None,
            "future": None,
        }
        self._jobs[job_id] = state

        def run() -> ChoiceProviderResult:
            state["started_at"] = time.time()
            if state.get("cancelled"):
                return ChoiceProviderResult(status="cancelled", provider_id=request.provider_id, error="Choice lookup was cancelled.")
            return resolve_choices(request, self.providers)

        future = self._executor.submit(run)
        state["future"] = future
        future.add_done_callback(lambda done, jid=job_id: self._complete(jid, done))
        return self.status(job_id)

    def cancel(self, job_id: str) -> ChoiceProviderJobSnapshot:
        state = self._jobs.get(job_id)
        if not state:
            return ChoiceProviderJobSnapshot(job_id=job_id, provider_id="", slot_name="", status="missing", created_at=0.0)
        state["cancelled"] = True
        future = state.get("future")
        if isinstance(future, Future):
            future.cancel()
        if state.get("status") in {"queued", "running"}:
            state["status"] = "cancelled"
            state["completed_at"] = time.time()
        return self.status(job_id)

    def status(self, job_id: str) -> ChoiceProviderJobSnapshot:
        state = self._jobs.get(job_id)
        if not state:
            return ChoiceProviderJobSnapshot(job_id=job_id, provider_id="", slot_name="", status="missing", created_at=0.0)
        future = state.get("future")
        if state.get("cancelled"):
            state["status"] = "cancelled"
        elif isinstance(future, Future) and future.running() and state.get("status") == "queued":
            state["status"] = "running"
        request = state.get("request")
        return ChoiceProviderJobSnapshot(
            job_id=job_id,
            provider_id=getattr(request, "provider_id", ""),
            slot_name=getattr(request, "slot_name", ""),
            status=str(state.get("status") or "queued"),
            created_at=float(state.get("created_at") or 0.0),
            started_at=float(state.get("started_at") or 0.0),
            completed_at=float(state.get("completed_at") or 0.0),
            cancelled=bool(state.get("cancelled")),
            result=state.get("result"),
            error=state.get("error"),
        )

    def result(self, job_id: str) -> ChoiceProviderResult | None:
        return self.status(job_id).result

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _complete(self, job_id: str, future: Future) -> None:
        state = self._jobs.get(job_id)
        if not state:
            return
        state["completed_at"] = time.time()
        if state.get("cancelled") or future.cancelled():
            state["status"] = "cancelled"
            if not state.get("result"):
                request = state.get("request")
                state["result"] = ChoiceProviderResult(
                    status="cancelled",
                    provider_id=getattr(request, "provider_id", ""),
                    error="Choice lookup was cancelled.",
                )
            return
        try:
            state["result"] = future.result()
            state["status"] = state["result"].status or "loaded"
        except Exception as exc:
            request = state.get("request")
            state["status"] = "failed"
            state["error"] = str(exc)
            state["result"] = ChoiceProviderResult(
                status="failed",
                provider_id=getattr(request, "provider_id", ""),
                error=str(exc),
                recovery_options=[RecoveryOption("retry", "Retry", requires_refresh=True)],
            )


CHOICE_PROVIDER_JOBS = ChoiceProviderJobManager()


def resolve_choices(request: ChoiceProviderRequest, providers: dict[str, ChoiceProvider] | None = None) -> ChoiceProviderResult:
    providers = providers or CHOICE_PROVIDERS
    provider = providers.get(request.provider_id)
    if not provider:
        return ChoiceProviderResult(
            status="failed",
            provider_id=request.provider_id,
            error=f"No choice provider registered for {request.provider_id}.",
            recovery_options=[],
        )
    started = time.perf_counter()
    result = provider.choices(request)
    result.provider_id = result.provider_id or request.provider_id
    result.latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return result


def choice_item(
    value: Any,
    *,
    group: str = "",
    is_recommended: bool = False,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChoiceItem:
    label = _label_for_value(value)
    return ChoiceItem(
        value=value,
        label=label,
        detail=str(value) if str(value) != label else "",
        group=group,
        search_terms=(label, str(value)),
        metadata=metadata or {},
        is_recommended=is_recommended,
        confidence=confidence,
    )


def _result(provider_id: str, choices: list[ChoiceItem], *, status: str = "", refresh_policy: str = "manual") -> ChoiceProviderResult:
    return ChoiceProviderResult(
        status=status or ("loaded" if choices else "empty"),
        choices=choices,
        provider_id=provider_id,
        is_stale=False,
        can_refresh=refresh_policy != "never",
        refresh_policy=refresh_policy,
    )


def _label_for_value(value: Any) -> str:
    if isinstance(value, dict):
        raw = str(value.get("label") or value.get("name") or value.get("path") or value.get("value") or value)
    else:
        raw = str(value)
    raw = raw.strip()
    if "/" in raw:
        raw = raw.rstrip("/").split("/")[-1]
    if "|" in raw:
        raw = raw.rstrip("|").split("|")[-1]
    if "." in raw and not raw.lower().endswith((".py", ".json", ".txt", ".md", ".uasset")):
        raw = raw.split(".")[-1]
    return raw or "value"


def _lines_from_raw(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _dedupe_choices(choices: list[ChoiceItem]) -> list[ChoiceItem]:
    seen: set[str] = set()
    out: list[ChoiceItem] = []
    for choice in choices:
        key = repr(choice.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(choice)
    return out
