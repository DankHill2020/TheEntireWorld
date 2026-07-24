"""LLM routing with a stable provider/model selection for each prompt run."""

from dataclasses import dataclass
from contextvars import ContextVar
from functools import wraps
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional


@dataclass(frozen=True)
class LLMProviderRoute:
    """Resolved provider contract that can be reused for an entire prompt run."""

    provider: str
    model: str
    api_key: str = ""
    cloud_active: bool = False


class LLMCloudProviderError(RuntimeError):
    """A locked cloud provider failed and was deliberately not replaced."""


_CLOUD_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.5-flash",
}
_ACTIVE_PROVIDER_ROUTE: ContextVar[Optional[LLMProviderRoute]] = ContextVar(
    "tech_connector_llm_provider_route",
    default=None,
)
_ACTIVE_MODEL_CALLS: ContextVar[Optional[list[dict[str, Any]]]] = ContextVar(
    "tech_connector_llm_model_calls",
    default=None,
)
_ACTIVE_PROVIDER_FAILURE: ContextVar[Optional[str]] = ContextVar(
    "tech_connector_llm_provider_failure",
    default=None,
)


def _public_route(route: LLMProviderRoute) -> dict[str, Any]:
    return {
        "provider": route.provider,
        "model": route.model,
        "cloud_active": route.cloud_active,
        "fallback_allowed": False,
    }


def current_llm_provider_route() -> Optional[LLMProviderRoute]:
    return _ACTIVE_PROVIDER_ROUTE.get()


def assert_llm_provider_healthy() -> None:
    failure = _ACTIVE_PROVIDER_FAILURE.get()
    if failure:
        raise LLMCloudProviderError(failure)


def lock_llm_provider_for_prompt(function):
    """Freeze one provider/model and attach model-call telemetry to the result."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        from tech_connector.services.settings_service import load_settings

        settings = load_settings()
        selected = str(
            settings.get("model")
            or settings.get("cloud_provider_model")
            or settings.get("general_model")
            or "qwen3:8b"
        )
        route = resolve_llm_provider_route(selected, settings)
        route_token = _ACTIVE_PROVIDER_ROUTE.set(route)
        calls: list[dict[str, Any]] = []
        calls_token = _ACTIVE_MODEL_CALLS.set(calls)
        failure_token = _ACTIVE_PROVIDER_FAILURE.set(None)
        try:
            result = function(*args, **kwargs)
            metadata = getattr(result, "metadata", None)
            if isinstance(metadata, dict):
                metadata["llm_provider_lock"] = _public_route(route)
                metadata["llm_model_calls"] = list(calls)
                metadata["llm_provider_integrity"] = {
                    "valid": all(
                        call.get("provider") == route.provider
                        and (
                            not route.cloud_active
                            or call.get("model") == route.model
                        )
                        for call in calls
                    ),
                    "call_count": len(calls),
                    "unexpected_routes": [
                        call
                        for call in calls
                        if call.get("provider") != route.provider
                        or (
                            route.cloud_active
                            and call.get("model") != route.model
                        )
                    ],
                }
                result.metadata = metadata
            return result
        finally:
            _ACTIVE_PROVIDER_FAILURE.reset(failure_token)
            _ACTIVE_MODEL_CALLS.reset(calls_token)
            _ACTIVE_PROVIDER_ROUTE.reset(route_token)

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
        aliases = {"google": "gemini", "gemini": "gemini"}
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
    local_model = str(requested_model or settings.get("general_model") or "qwen3:8b")
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
    }
    requested_provider, requested_name = _provider_from_model(local_model)
    if requested_provider and credentials.get(requested_provider):
        return LLMProviderRoute(
            requested_provider,
            requested_name or _CLOUD_DEFAULT_MODELS[requested_provider],
            credentials[requested_provider],
            True,
        )
    configured_model = str(settings.get("cloud_provider_model") or "").strip()
    provider, model_name = _provider_from_model(configured_model)
    if provider and credentials.get(provider):
        return LLMProviderRoute(
            provider,
            model_name or _CLOUD_DEFAULT_MODELS[provider],
            credentials[provider],
            True,
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
    if requested_provider and not credentials.get(requested_provider):
        print(
            f"\n[WARNING] Cloud model '{local_model}' was requested, but no API key is configured "
            f"for '{requested_provider}'. Falling back to local Ollama.\n",
            file=sys.stderr,
            flush=True,
        )
    elif provider and not credentials.get(provider):
        print(
            f"\n[WARNING] Configured cloud model '{configured_model}' has no API key configured "
            f"for '{provider}'. Falling back to local Ollama.\n",
            file=sys.stderr,
            flush=True,
        )

    return LLMProviderRoute("ollama", local_model)


def generate_llm_response(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[dict | str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45,
    *,
    provider_route: Optional[LLMProviderRoute] = None,
    allow_cloud_fallback: bool = False,
) -> str:
    """Generate a response without changing an active cloud route mid-run."""
    from tech_connector.services.settings_service import load_settings
    settings = load_settings()
    active_route = current_llm_provider_route()
    route = (
        provider_route
        if provider_route is not None and provider_route.cloud_active
        else active_route
        if active_route is not None and active_route.cloud_active
        else LLMProviderRoute("ollama", model)
        if active_route is not None
        else resolve_llm_provider_route(model, settings)
    )
    if route.cloud_active:
        assert_llm_provider_healthy()
    call_event = {
        "provider": route.provider,
        "model": route.model,
        "cloud_active": route.cloud_active,
        "started_at_monotonic": round(time.monotonic(), 6),
        "status": "running",
    }
    active_calls = _ACTIVE_MODEL_CALLS.get()
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
            )
            call_event["status"] = "completed"
            call_event["response_characters"] = len(value)
            return value
        except Exception:
            call_event["status"] = "failed"
            raise
        finally:
            call_event["elapsed_seconds"] = round(time.monotonic() - started, 3)

    try:
        if route.provider == "openai":
            value = _query_openai(route.model, route.api_key, prompt, system, response_format, options, timeout)
        elif route.provider == "anthropic":
            value = _query_anthropic(route.model, route.api_key, prompt, system, response_format, options, timeout)
        elif route.provider == "gemini":
            value = _query_gemini(route.model, route.api_key, prompt, system, response_format, options, timeout)
        else:
            raise ValueError(f"Unsupported cloud provider: {route.provider}")
        call_event["status"] = "completed"
        call_event["response_characters"] = len(value)
        return value
    except Exception as e:
        call_event["status"] = "failed"
        call_event["error_type"] = type(e).__name__
        if allow_cloud_fallback:
            local_fallback_model = settings.get("fallback_general_model", "qwen2.5-coder:latest")
            print(
                f"[LLMRouter] Explicit cloud fallback enabled after {route.provider} "
                f"failure: {e}",
                file=sys.stderr,
                flush=True,
            )
            return _query_ollama(local_fallback_model, prompt, system, response_format, options, timeout)
        message = (
            f"{route.provider}:{route.model} failed; provider lock prevented "
            f"a local fallback: {e}"
        )
        if _ACTIVE_PROVIDER_ROUTE.get() is not None:
            _ACTIVE_PROVIDER_FAILURE.set(message)
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
    active_route = current_llm_provider_route()
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




def _query_ollama(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    """Fallback local Ollama call."""
    from tech_connector.services.ollama_service import OLLAMA_BASE_URL, ensure_ollama_server, normalize_ollama_model_name
    ensure_ollama_server()

    payload_dict = {
        "model": normalize_ollama_model_name(model),
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload_dict["system"] = system
    if response_format == "json":
        payload_dict["format"] = "json"
    elif isinstance(response_format, dict):
        payload_dict["format"] = response_format
    if options:
        payload_dict["options"] = options

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    with opener.open(req, timeout=timeout) as response:
        resp = json.loads(response.read().decode("utf-8"))
        return str(resp.get("response") or "")


def _query_openai(
    model: str,
    api_key: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[dict | str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload_dict = {
        "model": model,
        "messages": messages,
    }
    if response_format == "json":
        payload_dict["response_format"] = {"type": "json_object"}
    elif isinstance(response_format, dict):
        payload_dict["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "tech_connector_response",
                # Planner schemas intentionally allow forward-compatible fields.
                # Strict mode would reject that schema before the model runs.
                "strict": False,
                "schema": response_format,
            },
        }
    if options and "temperature" in options:
        payload_dict["temperature"] = float(options["temperature"])

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
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
            return str(resp["choices"][0]["message"]["content"])
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
