from __future__ import annotations

import pytest

from tech_connector.services.modular_provider_utils import invoke_custom_provider


def test_configured_provider_can_fail_strictly_without_default_fallback() -> None:
    def fallback() -> str:
        return "fallback"

    with pytest.raises(RuntimeError, match="Could not resolve custom provider"):
        invoke_custom_provider(
            "tech_connector.services.custom_providers.missing_provider.call",
            fallback,
            allow_fallback=False,
        )


def test_unconfigured_provider_still_uses_fallback() -> None:
    def fallback() -> str:
        return "fallback"

    assert invoke_custom_provider("default", fallback) == "fallback"
