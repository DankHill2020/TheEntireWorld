"""Verify the account-backed OpenAI route honors a process-local Fast profile.

Run from the Windows identity that owns the signed-in OpenAI account. This
probe sends only a fixed one-word prompt and does not edit project files.
"""

from __future__ import annotations

import json
import time

from tech_connector.services import settings_service
from tech_connector.services.llm_router_service import (
    LLMProviderRoute,
    generate_llm_response,
)


def main() -> None:
    settings_service.load_settings = lambda: {"code_prompt_depth": "fast"}
    route = LLMProviderRoute(
        "openai", "gpt-6-luna", cloud_active=True, transport="account",
    )
    started = time.perf_counter()
    response = generate_llm_response(
        "openai:gpt-6-luna",
        "Reply with the exact word READY and nothing else.",
        provider_route=route,
        timeout=75,
        _queue_bypass=True,
    )
    print(json.dumps({
        "exact_ready": response.strip() == "READY",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }))


if __name__ == "__main__":
    main()
