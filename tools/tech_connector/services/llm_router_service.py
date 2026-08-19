"""LLM routing with a stable provider/model selection for each prompt run."""

from __future__ import annotations

from functools import wraps
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional

from reasoning_runtime.models import (
    ModelProviderLockError as LLMCloudProviderError,
    ModelProviderRoute as LLMProviderRoute,
    assert_model_provider_healthy,
    current_model_calls,
    current_model_provider_route,
    locked_model_provider_route,
    mark_model_provider_failed,
    model_provider_integrity,
    public_provider_route,
)


_CLOUD_DEFAULT_MODELS = {
    "openai": "gpt-5.6-sol",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.5-flash",
    "x": "grok-4.5",
}
def _public_route(route: LLMProviderRoute) -> dict[str, Any]:
    return public_provider_route(route)


def current_llm_provider_route() -> Optional[LLMProviderRoute]:
    return current_model_provider_route()


def assert_llm_provider_healthy() -> None:
    assert_model_provider_healthy()


def lock_llm_provider_for_prompt(function):
    """Freeze one provider/model and attach model-call telemetry to the result."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        owner = args[0] if args else None
        route = getattr(owner, "_prompt_provider_route", None)
        if route is None:
            from tech_connector.services.settings_service import load_settings

            settings = load_settings()
            selected = str(
                settings.get("model")
                or settings.get("cloud_provider_model")
                or settings.get("general_model")
                or "qwen3:4b-instruct"
            )
            route = resolve_llm_provider_route(selected, settings)
        with locked_model_provider_route(route) as calls:
            result = function(*args, **kwargs)
            metadata = getattr(result, "metadata", None)
            if isinstance(metadata, dict):
                metadata["llm_provider_lock"] = _public_route(route)
                metadata["llm_model_calls"] = list(calls)
                metadata["llm_provider_integrity"] = model_provider_integrity(route, calls)
                result.metadata = metadata
            return result

    return wrapped


def _credential(settings: dict[str, Any], setting: str, *env_vars: str) -> str:
    for env_var in env_vars:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return str(settings.get(setting, "") or "").strip()


def _provider_from_model(model: str) -> tuple[str, str]:
    value = str(model or "").strip()
    if ":" in value:
        prefix, model_name = value.split(":", 1)
        aliases = {
            "google": "gemini",
            "gemini": "gemini",
            "grok": "x",
            "xai": "x",
        }
        provider = aliases.get(prefix.lower(), prefix.lower())
        if provider in _CLOUD_DEFAULT_MODELS:
            normalized_name = model_name.strip()
            if provider == "gemini" and normalized_name.lower() == "gemini-1.5-pro":
                normalized_name = "gemini-2.5-flash"
            if provider == "anthropic" and normalized_name.lower() in {
                "claude-3-5-sonnet-latest",
                "claude-sonnet-4-20250514",
            }:
                normalized_name = _CLOUD_DEFAULT_MODELS["anthropic"]
            return provider, normalized_name
    lowered = value.lower()
    if "gemini" in lowered:
        if lowered in {"gemini-1.5-pro", "google:gemini-1.5-pro"}:
            return "gemini", "gemini-2.5-flash"
        return "gemini", value
    if "claude" in lowered:
        if lowered in {
            "claude-3-5-sonnet-latest",
            "claude-sonnet-4-20250514",
        }:
            return "anthropic", _CLOUD_DEFAULT_MODELS["anthropic"]
        return "anthropic", value
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai", value
    if lowered.startswith("grok-"):
        return "x", value
    return "", value


def resolve_llm_provider_route(
    requested_model: str,
    settings: Optional[dict[str, Any]] = None,
) -> LLMProviderRoute:
    """Resolve one provider/model pair for the complete prompt lifecycle."""
    if settings is None:
        from tech_connector.services.settings_service import load_settings

        settings = load_settings()
    settings = settings or {}
    from tech_connector.services.ollama_service import resolve_ollama_model_name

    local_model = str(requested_model or settings.get("general_model") or "qwen3:4b-instruct")
    local_model = resolve_ollama_model_name(local_model)
    fallback_local_model = str(
        settings.get("ollama_model")
        or settings.get("fallback_general_model")
        or settings.get("fast_general_model")
        or settings.get("router_fast_llm_model")
        or "qwen3:4b-instruct"
    )
    fallback_local_model = resolve_ollama_model_name(
        fallback_local_model.removeprefix("ollama:").strip()
    )
    if _provider_from_model(fallback_local_model)[0]:
        fallback_local_model = "qwen3:4b-instruct"
    if (
        settings.get("model_source_mode") == "local_only"
        or settings.get("local_only") is True
    ):
        return LLMProviderRoute("ollama", local_model)

    credentials = {
        "openai": _credential(settings, "openai_api_key", "OPENAI_API_KEY"),
        "anthropic": _credential(settings, "anthropic_api_key", "ANTHROPIC_API_KEY"),
        "gemini": (
            _credential(
                settings,
                "gemini_api_key",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
            )
            or str(settings.get("google_api_key") or "").strip()
        ),
        "x": _credential(settings, "xai_api_key", "XAI_API_KEY"),
    }
    requested_provider, requested_name = _provider_from_model(requested_model or "")
    if requested_model and requested_model.startswith("ollama:"):
        return LLMProviderRoute("ollama", local_model)

    target_provider = requested_provider
    target_name = requested_name
    if not target_provider:
        configured_model = str(settings.get("cloud_provider_model") or "").strip()
        c_provider, c_name = _provider_from_model(configured_model)
        if c_provider:
            target_provider, target_name = c_provider, c_name
        else:
            return LLMProviderRoute("ollama", local_model)

    if (
        target_provider == "openai"
        and bool(settings.get("auto_select_openai_model_by_depth", True))
        and (
            not target_name
            or str(target_name).lower().startswith(("gpt-5.6", "gpt-5.3-codex"))
        )
    ):
        from tech_connector.services.code_prompt_profile_service import (
            preferred_openai_model,
        )

        target_name = preferred_openai_model(
            str(settings.get("code_prompt_depth") or "balanced")
        )

    target_account_provider = (
        "google" if target_provider == "gemini" else target_provider
    )
    if target_account_provider:
        import tech_connector.services.authenticated_provider_service as auth_svc

        if auth_svc.account_provider_is_connected(target_account_provider):
            return LLMProviderRoute(
                target_provider,
                target_name or _CLOUD_DEFAULT_MODELS[target_provider],
                "",
                True,
                "account",
            )
    if target_provider and credentials.get(target_provider):
        return LLMProviderRoute(
            target_provider,
            target_name or _CLOUD_DEFAULT_MODELS[target_provider],
            credentials[target_provider],
            True,
            "api_key",
        )

    configured_providers = [
        name for name, credential in credentials.items() if credential
    ]
    if len(configured_providers) == 1:
        provider = configured_providers[0]
        return LLMProviderRoute(
            provider,
            _CLOUD_DEFAULT_MODELS[provider],
            credentials[provider],
            True,
        )

    # Warning for missing credentials if a cloud model was requested
    if target_provider:
        import tech_connector.services.authenticated_provider_service as auth_svc

        acc_provider = (
            "google" if target_provider == "gemini" else target_provider
        )
        if not auth_svc.account_provider_is_connected(
            acc_provider
        ) and not credentials.get(target_provider):
            print(
                f"\n[WARNING] Cloud model '{local_model}' was requested, but '{target_provider}' "
                f"is not connected via account login or optional API key. Falling back to local Ollama.\n",
                file=sys.stderr,
                flush=True,
            )

    return LLMProviderRoute("ollama", fallback_local_model)


def generate_llm_response(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[dict | str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 300,
    *,
    provider_route: Optional[LLMProviderRoute] = None,
    allow_cloud_fallback: bool = False,
    no_progress_seconds: int | None = None,
    max_wall_seconds: int | None = None,
    queue_category: str = "interactive",
    queue_priority: int | None = None,
    queue_request_id: str = "",
    queue_supersede_key: str = "",
    queue_cancel_event: Any = None,
    queue_deadline_seconds: float | None = None,
    _queue_bypass: bool = False,
    _queue_metadata: dict[str, Any] | None = None,
) -> str:
    """Generate through a bounded provider queue and a stable provider route.

    :param model: Requested model name.
    :param prompt: User or workflow prompt.
    :param system: Optional system prompt.
    :param response_format: Optional structured-output contract.
    :param options: Provider-specific generation options.
    :param timeout: Provider timeout and default queue-start deadline in seconds.
    :param provider_route: Optional already-resolved provider route.
    :param allow_cloud_fallback: Whether cloud failure may enqueue local fallback.
    :param no_progress_seconds: Local streaming no-progress limit.
    :param max_wall_seconds: Optional stricter local provider wall limit.
    :param queue_category: Scheduling category such as interactive or background.
    :param queue_priority: Optional explicit scheduling priority.
    :param queue_request_id: Optional request correlation identifier.
    :param queue_supersede_key: Optional key for replacing stale queued work.
    :param queue_cancel_event: Optional cancellation event.
    :param queue_deadline_seconds: Optional queue-start deadline overriding timeout.
    :return: Generated response text.
    """

    from tech_connector.services.settings_service import load_settings
    settings = load_settings()
    active_route = current_model_provider_route()
    route = (
        provider_route
        if provider_route is not None
        else active_route
        if active_route is not None and active_route.cloud_active
        else LLMProviderRoute("ollama", model)
        if active_route is not None
        else resolve_llm_provider_route(model, settings)
    )
    if not _queue_bypass:
        from tech_connector.services.llm_request_queue_service import (
            global_llm_request_queue,
            llm_queue_lane_options,
        )

        request_id = str(queue_request_id or uuid.uuid4())
        queued_at = time.monotonic()
        import threading

        submitting_thread_id = threading.get_ident()
        _INFERENCE_METRICS_BY_THREAD.pop(submitting_thread_id, None)
        transferred_metrics: dict[str, Any] = {}
        total_deadline = max(
            0.001,
            float(
                queue_deadline_seconds
                if queue_deadline_seconds is not None
                else timeout
            ),
        )
        lane_options = llm_queue_lane_options(settings, route.provider)

        def execute_queued_request() -> str:
            queue_wait = max(0.0, time.monotonic() - queued_at)
            remaining = max(1, int(total_deadline - queue_wait))
            effective_wall = (
                min(float(max_wall_seconds), float(remaining))
                if max_wall_seconds is not None
                else remaining
            )
            try:
                return generate_llm_response(
                    model,
                    prompt,
                    system,
                    response_format,
                    options,
                    min(int(timeout), remaining),
                    provider_route=route,
                    allow_cloud_fallback=allow_cloud_fallback,
                    no_progress_seconds=no_progress_seconds,
                    max_wall_seconds=effective_wall,
                    queue_category=queue_category,
                    queue_priority=queue_priority,
                    queue_request_id=request_id,
                    queue_supersede_key=queue_supersede_key,
                    queue_cancel_event=queue_cancel_event,
                    queue_deadline_seconds=remaining,
                    _queue_bypass=True,
                    _queue_metadata={
                        "queue_request_id": request_id,
                        "queue_category": str(queue_category or "interactive"),
                        "queue_priority": queue_priority,
                        "queue_wait_seconds": round(queue_wait, 6),
                    },
                )
            finally:
                worker_metrics = pop_last_inference_metrics()
                if worker_metrics:
                    transferred_metrics.update(worker_metrics)

        try:
            result = global_llm_request_queue().submit(
                execute_queued_request,
                provider=route.provider,
                model=route.model,
                category=queue_category,
                priority=queue_priority,
                **lane_options,
                deadline_seconds=total_deadline,
                request_id=request_id,
                supersede_key=queue_supersede_key,
                cancel_event=queue_cancel_event,
            )
            return result
        except LLMCloudProviderError as exc:
            # ContextVar state is copied into queue workers. Replay the provider
            # poison in the submitting context so swallowed stage failures still
            # stop the prompt run at its next health check.
            mark_model_provider_failed(str(exc))
            raise
        finally:
            if transferred_metrics:
                _INFERENCE_METRICS_BY_THREAD[submitting_thread_id] = dict(
                    transferred_metrics
                )
    if route.cloud_active:
        assert_model_provider_healthy()
    call_event = {
        "provider": route.provider,
        "model": route.model,
        "cloud_active": route.cloud_active,
        "started_at_monotonic": round(time.monotonic(), 6),
        "status": "running",
    }
    call_event.update(dict(_queue_metadata or {}))
    active_calls = current_model_calls()
    if active_calls is not None:
        active_calls.append(call_event)
    started = time.monotonic()
    if not route.cloud_active:
        try:
            value = _query_ollama(
                route.model,
                prompt,
                system,
                response_format,
                options,
                timeout,
                no_progress_seconds=no_progress_seconds,
                max_wall_seconds=max_wall_seconds,
            )
            call_event["status"] = "completed"
            call_event["response_characters"] = len(value)
            return value
        except Exception:
            call_event["status"] = "failed"
            raise
        finally:
            call_event["elapsed_seconds"] = round(time.monotonic() - started, 3)

    effective_options = dict(options or {})
    if route.provider == "openai":
        from tech_connector.services.code_prompt_profile_service import (
            normalize_code_prompt_profile,
            openai_execution_options,
        )

        profile = normalize_code_prompt_profile(settings=settings)
        defaults = openai_execution_options(profile)
        defaults["reasoning_context"] = str(
            settings.get("openai_reasoning_context")
            or defaults.get("reasoning_context")
            or "all_turns"
        )
        defaults["store"] = bool(settings.get("openai_store_responses", True))
        defaults.update(effective_options)
        effective_options = defaults

    try:
        if route.transport == "account":
            from tech_connector.services.authenticated_provider_service import (
                query_account_provider,
            )

            account_provider = "google" if route.provider == "gemini" else route.provider
            value = query_account_provider(
                account_provider,
                route.model,
                prompt,
                system,
                response_format,
                timeout,
            )
        elif route.provider == "openai":
            value = _query_openai(
                route.model,
                route.api_key,
                prompt,
                system,
                response_format,
                effective_options,
                timeout,
            )
        elif route.provider == "anthropic":
            value = _query_anthropic(route.model, route.api_key, prompt, system, response_format, options, timeout)
        elif route.provider == "gemini":
            value = _query_gemini(route.model, route.api_key, prompt, system, response_format, options, timeout)
        elif route.provider == "x":
            value = _query_xai(route.model, route.api_key, prompt, system, response_format, options, timeout)
        else:
            raise ValueError(f"Unsupported cloud provider: {route.provider}")
        call_event["status"] = "completed"
        call_event["response_characters"] = len(value)
        return value
    except Exception as e:
        call_event["status"] = "failed"
        call_event["error_type"] = type(e).__name__
        if allow_cloud_fallback:
            local_fallback_model = settings.get("fallback_general_model", "qwen3:4b-instruct")
            print(
                f"[LLMRouter] Explicit cloud fallback enabled after {route.provider} "
                f"failure: {e}",
                file=sys.stderr,
                flush=True,
            )
            return generate_llm_response(
                local_fallback_model,
                prompt,
                system=system,
                response_format=response_format,
                options=options,
                timeout=timeout,
                provider_route=LLMProviderRoute("ollama", local_fallback_model),
                allow_cloud_fallback=False,
                no_progress_seconds=no_progress_seconds,
                max_wall_seconds=max_wall_seconds,
                queue_category=queue_category,
                queue_priority=queue_priority,
                queue_request_id=f"{queue_request_id or uuid.uuid4()}:fallback",
                queue_cancel_event=queue_cancel_event,
            )
        message = (
            f"{route.provider}:{route.model} failed; provider lock prevented "
            f"a local fallback: {e}"
        )
        mark_model_provider_failed(message)
        raise LLMCloudProviderError(message) from e
    finally:
        call_event["elapsed_seconds"] = round(time.monotonic() - started, 3)


def query_structured_llm_until_complete(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    response_format: dict | str = "json",
    timeout: int = 1800,
    temperature: float = 0.0,
    num_ctx: int = 4096,
    progress_callback=None,
    prefer_coder: bool = True,
    coder_preference: str = "fast",
    max_wall_seconds: Optional[float] = None,
    provider_route: Optional[LLMProviderRoute] = None,
) -> str:
    """Run structured generation on one frozen cloud route or local Ollama."""
    active_route = current_model_provider_route()
    route = (
        provider_route
        if provider_route is not None and provider_route.cloud_active
        else active_route
        if active_route is not None and active_route.cloud_active
        else LLMProviderRoute("ollama", model)
        if active_route is not None
        else resolve_llm_provider_route(model)
    )
    wall_limit = (
        max(1, math.ceil(min(float(timeout), float(max_wall_seconds))))
        if max_wall_seconds is not None
        else timeout
    )
    if route.cloud_active:
        if progress_callback:
            progress_callback("", "")
        return generate_llm_response(
            route.model,
            user_prompt,
            system=system_prompt,
            response_format=response_format,
            options={"temperature": temperature, "thinking_budget": 512},
            timeout=wall_limit,
            provider_route=route,
            allow_cloud_fallback=False,
        )

    from tech_connector.knowledge.search import query_ollama_json_until_complete

    return query_ollama_json_until_complete(
        model=route.model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        num_ctx=num_ctx,
        timeout=timeout,
        temperature=temperature,
        progress_callback=progress_callback,
        prefer_coder=prefer_coder,
        coder_preference=coder_preference,
        response_format=response_format,
        max_wall_seconds=max_wall_seconds,
    )

_INFERENCE_METRICS_BY_THREAD: dict[int, dict[str, Any]] = {}


def pop_last_inference_metrics() -> dict[str, Any]:
    """Return and clear inference metrics owned by the current calling thread."""
    import threading

    return dict(_INFERENCE_METRICS_BY_THREAD.pop(threading.get_ident(), {}) or {})


def _query_ollama(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 300,
    *,
    no_progress_seconds: int | None = None,
    max_wall_seconds: int | None = None,
) -> str:
    """Generate locally through Ollama using streamed NDJSON responses.

    Stream events without generated text do not count as progress. A hard
    wall-clock ceiling prevents an active-but-unproductive stream from blocking
    the owning workflow indefinitely.
    """
    from tech_connector.services.ollama_service import (
        OLLAMA_BASE_URL,
        ensure_ollama_server,
        resolve_ollama_model_name,
    )

    ok, message = ensure_ollama_server()
    if not ok:
        raise RuntimeError(message)

    effective_options = dict(options or {})
    effective_options.setdefault("num_ctx", 4096)
    think = effective_options.pop("think", None)

    resolved_model = resolve_ollama_model_name(model)

    payload_dict: dict[str, Any] = {
        "model": resolved_model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": os.environ.get("AI_STUDIO_OLLAMA_KEEP_ALIVE", "15m"),
        "options": effective_options,
    }
    if system:
        payload_dict["system"] = system
    if think is not None:
        payload_dict["think"] = bool(think)
    if response_format == "json":
        payload_dict["format"] = "json"
    elif isinstance(response_format, dict):
        payload_dict["format"] = response_format

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    import queue
    import threading

    owner_thread_id = threading.get_ident()
    _INFERENCE_METRICS_BY_THREAD.pop(owner_thread_id, None)
    total_timeout = max(30, int(max_wall_seconds or timeout or 300))
    progress_timeout = max(
        15,
        int(no_progress_seconds or min(60, total_timeout)),
    )
    socket_timeout = min(total_timeout, max(30, progress_timeout))
    started = time.monotonic()
    state: dict[str, Any] = {
        "last_text_progress": started,
        "has_text": False,
        "first_text_at": None,
        "final_event": {},
        "response": None,
    }
    outcome: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def read_stream() -> None:
        chunks: list[str] = []
        try:
            with opener.open(req, timeout=socket_timeout) as response:
                state["response"] = response
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    event = json.loads(line)
                    if event.get("error"):
                        raise RuntimeError(str(event["error"]))

                    text = event.get("response")
                    if text:
                        chunks.append(str(text))
                        if state["first_text_at"] is None:
                            state["first_text_at"] = time.monotonic()
                        state["has_text"] = True
                        state["last_text_progress"] = time.monotonic()

                    if event.get("done"):
                        state["final_event"] = dict(event)
                        break
            outcome.put(("ok", "".join(chunks)))
        except BaseException as exc:
            outcome.put(("error", exc))

    worker = threading.Thread(
        target=read_stream,
        name=f"ollama-{resolved_model}-stream",
        daemon=True,
    )
    worker.start()
    timeout_error = ""
    while worker.is_alive():
        worker.join(timeout=0.25)
        now = time.monotonic()
        if now - started >= total_timeout:
            timeout_error = (
                f"Ollama call exceeded its {total_timeout}-second wall-clock "
                f"ceiling for {resolved_model}."
            )
            break
        allowed_silence = (
            progress_timeout
            if state["has_text"]
            else min(total_timeout, max(90, progress_timeout * 2))
        )
        if now - float(state["last_text_progress"]) >= allowed_silence:
            timeout_error = (
                f"Ollama produced no generated text for {allowed_silence} "
                f"seconds while running {resolved_model}."
            )
            break
    if timeout_error:
        _INFERENCE_METRICS_BY_THREAD[owner_thread_id] = {
            "model": resolved_model,
            "time_to_first_token_ms": (
                round(
                    (
                        float(state["first_text_at"]) - started
                    )
                    * 1000.0,
                    2,
                )
                if state["first_text_at"] is not None
                else None
            ),
            "wall_elapsed_ms": round((time.monotonic() - started) * 1000.0, 2),
            "timed_out": True,
            "input_chars": len(prompt) + len(system or ""),
        }
        active_response = state.get("response")
        if active_response is not None:
            try:
                active_response.close()
            except Exception:
                pass
        raise TimeoutError(timeout_error)

    try:
        status, value = outcome.get_nowait()
    except queue.Empty as exc:
        raise RuntimeError(
            f"Ollama stream ended without a result for {resolved_model}."
        ) from exc
    if status == "ok":
        final_event = dict(state.get("final_event") or {})
        prompt_tokens = int(final_event.get("prompt_eval_count") or 0)
        output_tokens = int(final_event.get("eval_count") or 0)
        prompt_ingestion_ns = int(final_event.get("prompt_eval_duration") or 0)
        generation_ns = int(final_event.get("eval_duration") or 0)
        _INFERENCE_METRICS_BY_THREAD[owner_thread_id] = {
            "model": resolved_model,
            "time_to_first_token_ms": (
                round(
                    (
                        float(state["first_text_at"]) - started
                    )
                    * 1000.0,
                    2,
                )
                if state["first_text_at"] is not None
                else None
            ),
            "prompt_ingestion_ms": round(prompt_ingestion_ns / 1_000_000.0, 2),
            "generation_ms": round(generation_ns / 1_000_000.0, 2),
            "wall_elapsed_ms": round((time.monotonic() - started) * 1000.0, 2),
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "tokens_per_second": (
                round(output_tokens / (generation_ns / 1_000_000_000.0), 2)
                if output_tokens and generation_ns
                else 0.0
            ),
            "input_chars": len(prompt) + len(system or ""),
            "output_chars": len(str(value)),
            "timed_out": False,
        }
        return str(value)
    exc = value
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code == 404:
            raise RuntimeError(
                f"Ollama model '{resolved_model}' not found. "
                f"Response: {detail or exc.reason}"
            ) from exc
        raise RuntimeError(
            f"Ollama request failed with HTTP {exc.code} for '{resolved_model}': "
            f"{detail or exc.reason}"
        ) from exc
    if isinstance(exc, TimeoutError):
        raise TimeoutError(
            f"Ollama generation timed out while running "
            f"{payload_dict['model']}: {exc}"
        ) from exc
    raise exc

def _query_openai(
    model: str,
    api_key: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[dict | str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    """Generate through OpenAI's Responses API.

    :param model: OpenAI model identifier.
    :param api_key: OpenAI API key.
    :param prompt: User input.
    :param system: Optional developer instructions.
    :param response_format: Optional JSON response contract.
    :param options: Reasoning, verbosity, continuation, and storage options.
    :param timeout: HTTP timeout in seconds.
    :return: Assistant output text.
    """

    effective_options = dict(options or {})
    payload_dict: dict[str, Any] = {
        "model": model,
        "input": prompt,
    }
    if system:
        payload_dict["instructions"] = system

    text_options: dict[str, Any] = {}
    verbosity = str(effective_options.get("verbosity") or "").strip().lower()
    if verbosity in {"low", "medium", "high"}:
        text_options["verbosity"] = verbosity
    if response_format == "json":
        text_options["format"] = {"type": "json_object"}
    elif isinstance(response_format, dict):
        text_options["format"] = {
            "type": "json_schema",
            "name": "tech_connector_response",
            "strict": False,
            "schema": response_format,
        }
    if text_options:
        payload_dict["text"] = text_options

    reasoning: dict[str, Any] = {}
    effort = str(effective_options.get("reasoning_effort") or "").strip().lower()
    if effort in {"none", "low", "medium", "high", "xhigh", "max"}:
        reasoning["effort"] = effort
    context = str(effective_options.get("reasoning_context") or "").strip().lower()
    if context in {"auto", "current_turn", "all_turns"}:
        reasoning["context"] = context
    mode = str(effective_options.get("reasoning_mode") or "").strip().lower()
    if mode == "pro":
        reasoning["mode"] = "pro"
    if reasoning:
        payload_dict["reasoning"] = reasoning

    previous_response_id = str(
        effective_options.get("previous_response_id") or ""
    ).strip()
    if previous_response_id:
        payload_dict["previous_response_id"] = previous_response_id
    if "store" in effective_options:
        payload_dict["store"] = bool(effective_options["store"])
    safety_identifier = str(
        effective_options.get("safety_identifier") or ""
    ).strip()
    if safety_identifier:
        payload_dict["safety_identifier"] = safety_identifier

    # Retain compatibility for older non-reasoning models. GPT-5-family
    # Responses requests are controlled through reasoning rather than sampling.
    if (
        "temperature" in effective_options
        and not str(model or "").lower().startswith(("gpt-5", "o1", "o3", "o4"))
    ):
        payload_dict["temperature"] = float(effective_options["temperature"])

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        with opener.open(req, timeout=timeout) as response:
            resp = json.loads(response.read().decode("utf-8"))
            if isinstance(resp.get("output_text"), str) and resp["output_text"]:
                return str(resp["output_text"])
            chunks: list[str] = []
            refusals: list[str] = []
            for item in list(resp.get("output") or []):
                if not isinstance(item, dict):
                    continue
                for content in list(item.get("content") or []):
                    if not isinstance(content, dict):
                        continue
                    value = content.get("text")
                    if isinstance(value, str) and value:
                        chunks.append(value)
                    refusal = content.get("refusal")
                    if isinstance(refusal, str) and refusal:
                        refusals.append(refusal)
            if chunks:
                return "".join(chunks)
            if refusals:
                raise RuntimeError("OpenAI refused the request: " + " ".join(refusals))
            raise RuntimeError("OpenAI Responses API returned no output text.")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str((payload.get("error") or {}).get("message") or "")
        except Exception:
            detail = ""
        if api_key:
            detail = detail.replace(api_key, "[REDACTED]")

        # Check for credit/quota errors specifically
        is_quota = exc.code in {402, 429} or "quota" in detail.lower() or "credit" in detail.lower() or "billing" in detail.lower()
        if is_quota:
            warn_msg = "\n[WARNING] Cloud provider credits are unavailable or exhausted. Please check your API credits/billing details."
            raise RuntimeError(f"OpenAI API HTTP {exc.code} - Insufficient API Credits / Quota Exceeded. Detail: {detail}{warn_msg}") from exc

        suffix = f": {detail[:500]}" if detail else ""
        raise RuntimeError(f"OpenAI API HTTP {exc.code}{suffix}") from exc


def _query_xai(
    model: str,
    api_key: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[dict | str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45,
) -> str:
    """Generate through xAI's documented Responses API."""
    payload_dict: dict[str, Any] = {"model": model, "input": prompt}
    if system:
        payload_dict["instructions"] = system
    if isinstance(response_format, dict):
        payload_dict["text"] = {
            "format": {
                "type": "json_schema",
                "name": "tech_connector_response",
                "schema": response_format,
            }
        }
    payload = json.dumps(payload_dict).encode("utf-8")
    request = urllib.request.Request(
        "https://api.x.ai/v1/responses",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if isinstance(result.get("output_text"), str):
        return result["output_text"]
    chunks = []
    for item in result.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if text:
                chunks.append(str(text))
    if chunks:
        return "".join(chunks)
    raise RuntimeError("xAI returned no response text.")


def _query_anthropic(
    model: str,
    api_key: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    payload_dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
    }
    if system:
        payload_dict["system"] = system
    # Sonnet 5 rejects non-default sampling controls. Its adaptive reasoning is
    # steered through the prompt and system contract instead.
    if (
        options
        and "temperature" in options
        and not model.startswith("claude-sonnet-5")
    ):
        payload_dict["temperature"] = float(options["temperature"])

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        with opener.open(req, timeout=timeout) as response:
            resp = json.loads(response.read().decode("utf-8"))
            return "".join(
                str(block.get("text") or "")
                for block in resp.get("content", [])
                if isinstance(block, dict) and block.get("type") == "text"
            )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str((payload.get("error") or {}).get("message") or "")
        except Exception:
            detail = ""
        if api_key:
            detail = detail.replace(api_key, "[REDACTED]")

        # Check for credit/quota errors
        is_quota = exc.code in {402, 429} or "quota" in detail.lower() or "credit" in detail.lower() or "balance" in detail.lower()
        if is_quota:
            warn_msg = "\n[WARNING] Cloud provider credits are unavailable or exhausted. Please check your API credits/billing details."
            raise RuntimeError(f"Anthropic API HTTP {exc.code} - Insufficient API Credits / Quota Exceeded. Detail: {detail}{warn_msg}") from exc

        suffix = f": {detail[:500]}" if detail else ""
        raise RuntimeError(f"Anthropic API HTTP {exc.code}{suffix}") from exc


def _query_gemini(
    model: str,
    api_key: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[dict | str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    model_name = model if "/" in model else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent"
    payload_dict = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    if system:
        payload_dict["systemInstruction"] = {"parts": [{"text": system}]}

    gen_config = {}
    if response_format == "json" or isinstance(response_format, dict):
        gen_config["responseMimeType"] = "application/json"
    if isinstance(response_format, dict):
        gen_config["responseJsonSchema"] = response_format
    if options and "temperature" in options:
        gen_config["temperature"] = float(options["temperature"])
    if options and "num_predict" in options:
        gen_config["maxOutputTokens"] = max(
            64,
            min(8192, int(options["num_predict"])),
        )
    if "2.5" in model:
        gen_config["thinkingConfig"] = {
            "thinkingBudget": int((options or {}).get("thinking_budget", 256))
        }

    if gen_config:
        payload_dict["generationConfig"] = gen_config

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        with opener.open(req, timeout=timeout) as response:
            resp = json.loads(response.read().decode("utf-8"))
            candidates = list(resp.get("candidates") or [])
            if not candidates:
                raise RuntimeError(f"Gemini returned no candidates: {resp}")
            parts = list(dict(candidates[0].get("content") or {}).get("parts") or [])
            text_parts = [str(part.get("text") or "") for part in parts if part.get("text")]
            if not text_parts:
                raise RuntimeError(f"Gemini returned no text content: {resp}")
            return "".join(text_parts)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str((payload.get("error") or {}).get("message") or "")
        except Exception:
            detail = ""
        if api_key:
            detail = detail.replace(api_key, "[REDACTED]")

        # Check for credit/quota/limit errors
        is_quota = exc.code in {402, 429} or "quota" in detail.lower() or "credit" in detail.lower() or "limit" in detail.lower() or "exhausted" in detail.lower()
        if is_quota:
            warn_msg = "\n[WARNING] Cloud provider credits are unavailable or exhausted. Please check your API credits/billing details."
            raise RuntimeError(f"Gemini API HTTP {exc.code} - Insufficient API Credits / Quota Exceeded. Detail: {detail}{warn_msg}") from exc

        suffix = f": {detail[:500]}" if detail else ""
        raise RuntimeError(f"Gemini API HTTP {exc.code}{suffix}") from exc

# Generation-time evidence pause/resume integration.
if not getattr(generate_llm_response, "_tech_connector_evidence_wrapped", False):
    import inspect as _evidence_inspect

    _TECH_CONNECTOR_EVIDENCE_ROUTER_WRAPPED = True
    _generate_llm_response_without_evidence_resume = generate_llm_response
    _generate_llm_response_signature = _evidence_inspect.signature(
        _generate_llm_response_without_evidence_resume
    )

    def generate_llm_response(*args, **kwargs):
        """Generate a response and resume focused evidence requests in-place."""

        response = _generate_llm_response_without_evidence_resume(*args, **kwargs)
        try:
            bound = _generate_llm_response_signature.bind_partial(*args, **kwargs)
        except TypeError:
            return response
        prompt_key = next(
            (
                key
                for key in ("prompt", "messages", "user_prompt")
                if key in bound.arguments
            ),
            "",
        )
        if not prompt_key:
            return response
        original_prompt = bound.arguments[prompt_key]

        def invoke_model(replacement_prompt):
            replacement_kwargs = dict(kwargs)
            replacement_args = list(args)
            if prompt_key in replacement_kwargs:
                replacement_kwargs[prompt_key] = replacement_prompt
            else:
                parameter_names = list(
                    _generate_llm_response_signature.parameters
                )
                prompt_index = parameter_names.index(prompt_key)
                if prompt_index >= len(replacement_args):
                    replacement_kwargs[prompt_key] = replacement_prompt
                else:
                    replacement_args[prompt_index] = replacement_prompt
            return _generate_llm_response_without_evidence_resume(
                *replacement_args,
                **replacement_kwargs,
            )

        from tech_connector.services.generation_evidence_request_service import (
            resolve_and_resume_generation_response,
        )
        return resolve_and_resume_generation_response(
            response,
            invoke_model=invoke_model,
            original_prompt=original_prompt,
        )
    generate_llm_response._tech_connector_evidence_wrapped = True

