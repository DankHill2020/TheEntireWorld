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


PROVIDERS = {
    "ollama": ModelProvider(
        id="ollama",
        display_name="Ollama Local",
        env_vars=(),
        example_models=("ollama:qwen2.5-coder:1.5b", "ollama:qwen3:8b"),
        setup_url="https://ollama.com/download",
        setup_kind="local",
        credential_hint="Install Ollama locally. No cloud login is required.",
        can_auto_import_key=True,
    ),
    "openai": ModelProvider(
        id="openai",
        display_name="OpenAI",
        env_vars=("OPENAI_API_KEY",),
        example_models=("openai:gpt-4o-mini",),
        setup_url="https://platform.openai.com/api-keys",
        setup_kind="official_console_api_key",
        credential_hint="Open the official OpenAI API keys page, create a key, then set OPENAI_API_KEY.",
    ),
    "google": ModelProvider(
        id="google",
        display_name="Google Gemini",
        env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        example_models=("google:gemini-1.5-pro",),
        setup_url="https://aistudio.google.com/apikey",
        setup_kind="official_console_api_key_or_oauth",
        credential_hint="Open Google AI Studio to create a Gemini key. Google also supports OAuth flows for some Google APIs.",
    ),
    "anthropic": ModelProvider(
        id="anthropic",
        display_name="Anthropic",
        env_vars=("ANTHROPIC_API_KEY",),
        example_models=("anthropic:claude-3-5-sonnet-latest",),
        setup_url="https://console.anthropic.com/settings/keys",
        setup_kind="official_console_api_key",
        credential_hint="Open the official Anthropic Console keys page, create a key, then set ANTHROPIC_API_KEY.",
    ),
}


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
    return any(bool(os.environ.get(name)) for name in provider.env_vars)


def provider_status_lines() -> list[str]:
    lines = []
    for provider in PROVIDERS.values():
        if provider.id == "ollama":
            lines.append(f"{provider.display_name}: local")
            continue
        keys = ", ".join(provider.env_vars)
        state = "configured" if provider_has_credentials(provider.id) else f"missing env ({keys})"
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
            "Security note: the Studio will not scrape or auto-transfer API keys from provider web pages. "
            "Those pages intentionally show secrets only to the signed-in user. Use the official page, then "
            "paste/store the key through a deliberate local credential flow."
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

    if provider_has_credentials(provider_id):
        return {
            "provider": provider_id,
            "required": False,
            "status": f"{provider.display_name} credentials detected.",
            "action": "",
        }

    envs = " or ".join(provider.env_vars)
    return {
        "provider": provider_id,
        "required": True,
        "status": f"{provider.display_name} requires setup before this model can be used.",
        "action": f"Open Settings -> Model Providers and configure {envs}.",
    }


def normalize_model_policy(settings: Optional[dict]) -> str:
    mode = (settings or {}).get("model_source_mode") or AUTO_WITH_LOCAL_FALLBACK
    if mode not in {LOCAL_ONLY, AUTO_WITH_LOCAL_FALLBACK}:
        return AUTO_WITH_LOCAL_FALLBACK
    return mode


def should_force_local(settings: Optional[dict]) -> bool:
    settings = settings or {}
    return normalize_model_policy(settings) == LOCAL_ONLY or bool(settings.get("cloud_model_unavailable", False))


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
