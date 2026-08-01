"""Model provider account/status and local fallback policy."""

from dataclasses import dataclass
import os
from typing import Optional


LOCAL_ONLY = "local_only"
AUTO_WITH_LOCAL_FALLBACK = "auto_with_local_fallback"


@dataclass(frozen=True)
class ModelProvider:
    id: str
    display_name: str
    env_vars: tuple[str, ...]
    example_models: tuple[str, ...]
    setup_url: str = ""
    setup_kind: str = "api_key"
    credential_hint: str = ""
    can_auto_import_key: bool = False
    account_transport: str = ""


PROVIDERS = {
    "ollama": ModelProvider(
        id="ollama",
        display_name="Local",
        env_vars=(),
        example_models=("ollama:qwen2.5-coder:3b", "ollama:qwen3:4b-instruct"),
        setup_url="https://ollama.com/download",
        setup_kind="local",
        credential_hint="Install Ollama locally. No cloud login is required.",
        can_auto_import_key=True,
    ),
    "openai": ModelProvider(
        id="openai",
        display_name="OpenAI",
        env_vars=("OPENAI_API_KEY",),
        example_models=(
            "openai:gpt-5.6-sol",
            "openai:gpt-5.6-terra",
            "openai:gpt-5.6-luna",
            "openai:gpt-5.3-codex",
        ),
        setup_url="https://platform.openai.com/api-keys",
        setup_kind="account_login_or_api_key",
        credential_hint="Sign in keylessly with ChatGPT through the official Codex client (API key is an optional fallback).",
        account_transport="codex",
    ),
    "x": ModelProvider(
        id="x",
        display_name="X",
        env_vars=("XAI_API_KEY",),
        example_models=("x:grok-4.5", "x:grok-build-0.1"),
        setup_url="https://x.ai/cli",
        setup_kind="account_login_or_api_key",
        credential_hint="Sign in keylessly with your X or Grok account through Grok Build (API key is an optional fallback).",
        account_transport="grok",
    ),
    "google": ModelProvider(
        id="google",
        display_name="Google Gemini",
        env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        example_models=(
            "google:gemini-2.5-flash",
            "google:gemini-2.5-pro",
        ),
        setup_url="https://aistudio.google.com/apikey",
        setup_kind="account_login_or_api_key",
        credential_hint="Sign in keylessly with Google through the official Antigravity CLI (API key is an optional fallback).",
        account_transport="antigravity",
    ),
    "anthropic": ModelProvider(
        id="anthropic",
        display_name="Anthropic",
        env_vars=("ANTHROPIC_API_KEY",),
        example_models=(
            "anthropic:claude-sonnet-5",
            "anthropic:claude-haiku-4-5",
        ),
        setup_url="https://console.anthropic.com/settings/keys",
        setup_kind="account_login_or_api_key",
        credential_hint="Sign in keylessly with your Claude account through the official Claude client (API key is an optional fallback).",
        account_transport="claude",
    ),
}

PROVIDER_ORDER = ("ollama", "openai", "x", "google", "anthropic")


def models_for_provider(provider_id: str) -> tuple[str, ...]:
    """Return only models belonging to one UI provider category."""
    provider = PROVIDERS.get(provider_id)
    return provider.example_models if provider else ()


def provider_for_model(model: str) -> str:
    prefix = (model or "").split(":", 1)[0].lower()
    return prefix if prefix in PROVIDERS else "ollama"


def is_provider_model(model: str) -> bool:
    prefix = (model or "").split(":", 1)[0].lower()
    return prefix in PROVIDERS


def provider_has_credentials(provider_id: str) -> bool:
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return False
    if not provider.env_vars:
        return True
    if provider.account_transport:
        from tech_connector.services.authenticated_provider_service import (
            account_provider_is_connected,
        )

        if account_provider_is_connected(provider_id):
            return True
    return any(bool(os.environ.get(name)) for name in provider.env_vars)


def provider_status_lines() -> list[str]:
    lines = []
    for provider in PROVIDERS.values():
        if provider.id == "ollama":
            lines.append(f"{provider.display_name}: local")
            continue
        state = "connected" if provider_has_credentials(provider.id) else "not connected"
        lines.append(f"{provider.display_name}: {state}")
    return lines


def provider_setup_url(provider_id: str) -> str:
    provider = PROVIDERS.get(provider_id)
    return provider.setup_url if provider else ""


def provider_setup_notes(provider_id: str) -> str:
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return "Unknown provider."

    lines = [
        f"{provider.display_name}",
        "",
        provider.credential_hint,
    ]

    if provider.account_transport:
        lines.append("")
        lines.append("Preferred authentication: official account login")

    if provider.env_vars:
        lines.append("")
        lines.append("Credential environment variable(s):")
        lines.extend(f"- {name}" for name in provider.env_vars)

    if provider.setup_url:
        lines.append("")
        lines.append(f"Official setup page: {provider.setup_url}")

    if not provider.can_auto_import_key and provider.env_vars:
        lines.append("")
        lines.append(
            "Security note: Tech Connector does not read browser cookies or provider token files. "
            "API keys are an advanced fallback for direct API and unattended workflows."
        )

    return "\n".join(lines)


def credential_requirement_for_model(model: str, settings: Optional[dict]) -> dict:
    """Describe whether the selected model needs a user credential action."""
    provider_id = provider_for_model(model)
    provider = PROVIDERS.get(provider_id, PROVIDERS["ollama"])

    if should_force_local(settings):
        return {
            "provider": "ollama",
            "required": False,
            "status": "Using local Ollama because local mode/fallback is active.",
            "action": "",
        }

    if provider_id == "ollama":
        return {
            "provider": provider_id,
            "required": False,
            "status": "Local Ollama model selected.",
            "action": "",
        }

    settings = settings or {}
    advanced_key = str(
        settings.get(
            "xai_api_key" if provider_id == "x" else f"{provider_id}_api_key",
            "",
        )
        or (
            settings.get("gemini_api_key", "")
            if provider_id == "google"
            else ""
        )
    ).strip()
    if provider_has_credentials(provider_id) or advanced_key:
        return {
            "provider": provider_id,
            "required": False,
            "status": f"{provider.display_name} credentials detected.",
            "action": "",
        }

    return {
        "provider": provider_id,
        "required": True,
        "status": f"{provider.display_name} requires setup before this model can be used.",
        "action": "Open Settings -> Model Providers and sign in, or use an advanced API key.",
    }


def normalize_model_policy(settings: Optional[dict]) -> str:
    mode = (settings or {}).get("model_source_mode") or AUTO_WITH_LOCAL_FALLBACK
    if mode not in {LOCAL_ONLY, AUTO_WITH_LOCAL_FALLBACK}:
        return AUTO_WITH_LOCAL_FALLBACK
    return mode


def should_force_local(settings: Optional[dict]) -> bool:
    settings = settings or {}
    return normalize_model_policy(settings) == LOCAL_ONLY


def should_use_local_runtime(model: str, settings: Optional[dict]) -> bool:
    """Return whether current model policy should start/warm/install local Ollama models."""
    if should_force_local(settings):
        return True
    return provider_for_model(model) == "ollama"


def resolve_model_for_policy(model: str, local_model: str, settings: Optional[dict]) -> str:
    """Resolve a configured model under local-only/auto-fallback rules."""
    if should_force_local(settings):
        return local_model

    provider = provider_for_model(model)
    if provider != "ollama" and not provider_has_credentials(provider):
        return local_model

    return model or local_model


def is_credit_or_quota_failure(text: str) -> bool:
    text = (text or "").lower()
    markers = (
        "insufficient_quota",
        "quota exceeded",
        "credit",
        "billing",
        "payment required",
        "402",
        "rate limit",
        "too many requests",
        "resource exhausted",
    )
    return any(marker in text for marker in markers)


def cloud_provider_failure_notice(text: str, model: str = "") -> str:
    """Return a user-facing cloud failure without implying an automatic fallback."""
    lowered = str(text or "").lower()
    selected = f"`{model}`" if model else "the selected cloud model"
    if any(marker in lowered for marker in ("credit balance", "insufficient_quota", "billing", "payment required")):
        reason = "The provider reports that API credits are unavailable or exhausted."
        recovery = "Add API credits, select another funded cloud provider, or explicitly switch Source Mode to **Always local**."
    elif any(marker in lowered for marker in ("quota exceeded", "resource exhausted", "rate limit", "too many requests", "429")):
        reason = "The provider quota or rate limit is currently exhausted."
        recovery = "Wait for the quota window to reset, select another cloud provider, or explicitly switch Source Mode to **Always local**."
    elif any(marker in lowered for marker in ("unauthorized", "forbidden", "invalid api key", "authentication", "401", "403")):
        reason = "The provider rejected the configured credentials."
        recovery = "Refresh the provider login, verify the advanced API key, or select another configured provider."
    else:
        reason = "The provider could not complete the request."
        recovery = "Check the provider status and configuration, then retry or explicitly select another model."
    return (
        "## Cloud Model Unavailable\n\n"
        f"Selected model: {selected}\n\n"
        f"{reason}\n\n"
        "This request stopped on the selected cloud provider; no local fallback was used.\n\n"
        f"{recovery}"
    )
