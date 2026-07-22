"""LLM Router Service supporting Cloud AI with local Ollama fallback."""

import json
import os
import sys
import urllib.request
from typing import Any, Dict, Optional


def generate_llm_response(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    """Generate LLM response, routing to Cloud APIs or local Ollama with fallback."""
    from tech_connector.services.settings_service import load_settings
    settings = load_settings()

    # Determine mode
    local_only = (
        settings.get("model_source_mode") == "local_only" 
        or settings.get("local_only") is True
    )

    # 1. If local only, route to Ollama
    if local_only:
        return _query_ollama(model, prompt, system, response_format, options, timeout)

    # 2. Extract credentials
    openai_key = settings.get("openai_api_key", "").strip()
    anthropic_key = settings.get("anthropic_api_key", "").strip()
    gemini_key = settings.get("gemini_api_key", "").strip()
    cloud_model = settings.get("cloud_provider_model", "gpt-4o").strip()

    # Determine which provider to use based on key presence or model prefix
    provider = None
    if "claude" in cloud_model.lower() or anthropic_key:
        provider = "anthropic"
    elif "gemini" in cloud_model.lower() or gemini_key:
        provider = "gemini"
    elif openai_key:
        provider = "openai"

    if not provider:
        # Fallback to local Ollama if no cloud keys are configured
        return _query_ollama(model, prompt, system, response_format, options, timeout)

    try:
        if provider == "openai" and openai_key:
            return _query_openai(cloud_model, openai_key, prompt, system, response_format, options, timeout)
        elif provider == "anthropic" and anthropic_key:
            return _query_anthropic(cloud_model, anthropic_key, prompt, system, response_format, options, timeout)
        elif provider == "gemini" and gemini_key:
            return _query_gemini(cloud_model, gemini_key, prompt, system, response_format, options, timeout)
    except Exception as e:
        # Check if exception looks like a quota, credit, or connection limit issue
        err_msg = str(e).lower()
        is_quota_or_network_error = any(
            x in err_msg 
            for x in ("402", "429", "quota", "limit", "credit", "balance", "connection", "timeout")
        )
        
        if is_quota_or_network_error:
            print(f"[LLMRouter] Warning: Cloud API call failed ({e}). Falling back to local Ollama.", file=sys.stderr, flush=True)
            # Fallback to Ollama!
            # Use configured local fallback model if the specified model is cloud-only
            local_fallback_model = settings.get("fallback_general_model", "qwen2.5-coder:latest")
            return _query_ollama(local_fallback_model, prompt, system, response_format, options, timeout)
        else:
            # Raise other errors (e.g. prompt errors)
            raise

    # Catch-all fallback
    return _query_ollama(model, prompt, system, response_format, options, timeout)


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
    response_format: Optional[str] = None,
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
    with opener.open(req, timeout=timeout) as response:
        resp = json.loads(response.read().decode("utf-8"))
        return str(resp["choices"][0]["message"]["content"])


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
    if options and "temperature" in options:
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
    with opener.open(req, timeout=timeout) as response:
        resp = json.loads(response.read().decode("utf-8"))
        return str(resp["content"][0]["text"])


def _query_gemini(
    model: str,
    api_key: str,
    prompt: str,
    system: Optional[str] = None,
    response_format: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout: int = 45
) -> str:
    # Use standard models/gemini-1.5-pro style naming
    model_name = model if "/" in model else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={api_key}"

    full_prompt = f"System Instruction: {system}\n\nPrompt: {prompt}" if system else prompt
    payload_dict = {
        "contents": [{
            "parts": [{"text": full_prompt}]
        }]
    }
    
    gen_config = {}
    if response_format == "json":
        gen_config["responseMimeType"] = "application/json"
    if options and "temperature" in options:
        gen_config["temperature"] = float(options["temperature"])
        
    if gen_config:
        payload_dict["generationConfig"] = gen_config

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    with opener.open(req, timeout=timeout) as response:
        resp = json.loads(response.read().decode("utf-8"))
        return str(resp["candidates"][0]["content"]["parts"][0]["text"])
